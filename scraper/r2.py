"""Sobe os criativos em resolucao cheia pro Cloudflare R2.

O repositorio nao aguenta imagem original: a ~150 criativos novos por dia a
900 KB cada, sao uns 4 GB por mes. R2 aguenta — 10 GB gratis e, diferente de
S3, sem cobranca de trafego de saida, que e o que importa num site que serve
imagem.

As credenciais NUNCA entram no repositorio. Leia de variavel de ambiente ou
do arquivo `r2.config.json`, que esta no .gitignore.

    {
      "account_id": "...",
      "access_key_id": "...",
      "secret_access_key": "...",
      "bucket": "native-ads",
      "public_base": "https://pub-xxxxxxxx.r2.dev"
    }
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.request
from pathlib import Path

CONFIG_PADRAO = "r2.config.json"
MANIFESTO = "r2-enviadas.json"


class R2Indisponivel(RuntimeError):
    """Sem credencial ou sem biblioteca: o site cai pras URLs do CDN."""


def _ler_env_file(raiz: Path) -> dict[str, str]:
    """Le um .env simples (CHAVE=valor), se existir.

    Parser proprio de proposito: trazer python-dotenv so pra isso seria uma
    dependencia a mais num projeto que ja roda com tres. Formato suportado e
    o basico — comentario com #, aspas opcionais, nada de expansao de
    variavel. Quem precisa de mais usa variavel de ambiente de verdade.
    """
    arquivo = raiz / ".env"
    if not arquivo.exists():
        return {}
    valores: dict[str, str] = {}
    for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip().strip("'\"")
    return valores


def carregar_config(raiz: Path) -> dict:
    """Pega a configuracao do ambiente, do .env ou do arquivo local.

    Nessa ordem de prioridade: o ambiente de verdade manda, porque e assim
    que um CI injeta segredo sem escrever nada em disco.
    """
    do_arquivo_env = _ler_env_file(raiz)

    def ambiente(nome: str) -> str | None:
        return os.environ.get(nome) or do_arquivo_env.get(nome)

    do_ambiente = {
        "account_id": ambiente("R2_ACCOUNT_ID"),
        "access_key_id": ambiente("R2_ACCESS_KEY_ID"),
        "secret_access_key": ambiente("R2_SECRET_ACCESS_KEY"),
        "bucket": ambiente("R2_BUCKET"),
        "public_base": ambiente("R2_PUBLIC_BASE"),
    }
    if all(do_ambiente.values()):
        return do_ambiente

    arquivo = raiz / CONFIG_PADRAO
    if not arquivo.exists():
        raise R2Indisponivel(
            f"nao achei {CONFIG_PADRAO}, nem .env, nem as variaveis R2_*. "
            "Veja o README, secao 'Imagens em resolucao cheia'."
        )
    try:
        config = json.loads(arquivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise R2Indisponivel(f"{CONFIG_PADRAO} nao e JSON valido: {exc}") from exc

    faltando = [c for c in ("account_id", "access_key_id", "secret_access_key",
                            "bucket", "public_base") if not config.get(c)]
    if faltando:
        raise R2Indisponivel(f"{CONFIG_PADRAO} sem: {', '.join(faltando)}")
    return config


def cliente(config: dict):
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise R2Indisponivel(
            "boto3 nao instalado: .venv/Scripts/python -m pip install boto3"
        ) from exc

    return boto3.client(
        "s3",
        endpoint_url=f"https://{config['account_id']}.r2.cloudflarestorage.com",
        aws_access_key_id=config["access_key_id"],
        aws_secret_access_key=config["secret_access_key"],
        # R2 ignora regiao mas o boto3 exige uma; 'auto' e o que a Cloudflare pede.
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


def baixar(url: str) -> bytes | None:
    """Puxa a imagem na melhor qualidade disponivel, direto da rede.

    Nao guardamos mais copia local de tudo: a imagem so e buscada quando o
    criativo prova que vale (3+ dias no ar), e nesse momento ele acabou de ser
    visto, entao a URL esta fresca.

    Tenta a origem antes da versao transformada — a origem e o arquivo que o
    anunciante subiu, a transformada e o recorte do slot. User-Agent de
    navegador porque CDN costuma recusar cliente de script.
    """
    from .images import candidates

    for candidata in candidates(url):
        pedido = urllib.request.Request(candidata, headers={"User-Agent": NAVEGADOR})
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                dados = resposta.read()
        except Exception:  # noqa: BLE001
            continue
        if len(dados) >= 1024:  # abaixo disso e pixel de tracking
            return dados
    return None


def _manifesto(raiz: Path) -> Path:
    return raiz / "data" / MANIFESTO


def ler_manifesto(raiz: Path) -> dict[str, str]:
    """O que ja subiu, pra nao reenviar a base inteira toda vez."""
    arquivo = _manifesto(raiz)
    if not arquivo.exists():
        return {}
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def gravar_manifesto(raiz: Path, enviadas: dict[str, str]) -> None:
    _manifesto(raiz).write_text(
        json.dumps(enviadas, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def enviar(raiz: Path, rows: list[dict], min_dias: int = 3, limite: int = 0,
           verbose: bool = True) -> dict[str, dict]:
    """Baixa e sobe os criativos que provaram valor. Devolve {fingerprint: info}.

    So entra criativo que sobreviveu `min_dias` coletas. A maioria aparece uma
    vez e some: guardar os 92% que nao voltam encheria o bucket em dois meses,
    enquanto guardar so os que ficam estica pra anos. Quem nao passou do corte
    continua aparecendo no site pela URL de origem do CDN.

    A imagem e buscada **na hora de subir**, nao na coleta. Quando um criativo
    cruza o limiar ele acabou de ser visto, entao a URL esta viva — e assim o
    disco local nao acumula gigabytes de criativo que apareceu uma vez so.

    Incremental: consulta o manifesto antes, entao publicar de novo custa o
    que mudou, nao a base inteira.
    """
    from .images import measure

    config = carregar_config(raiz)
    s3 = cliente(config)
    bucket = config["bucket"]
    base = config["public_base"].rstrip("/")

    enviadas = ler_manifesto(raiz)
    pendentes = []
    abaixo_do_corte = 0
    for row in rows:
        impressao = row.get("fingerprint")
        url = row.get("image_url")
        if not impressao or not url or impressao in enviadas:
            continue
        if (row.get("days_seen") or 1) < min_dias:
            abaixo_do_corte += 1
            continue
        pendentes.append((impressao, url))

    if limite:
        pendentes = pendentes[:limite]
    if not pendentes:
        if verbose:
            print(f"[r2] nada novo com {min_dias}+ dias "
                  f"({len(enviadas)} ja no bucket, {abaixo_do_corte} abaixo do corte)")
        return {k: _info(base, v) for k, v in enviadas.items()}

    if verbose:
        print(f"[r2] baixando e enviando {len(pendentes)} criativos com "
              f"{min_dias}+ dias; {abaixo_do_corte} abaixo do corte ficam no CDN")

    falhas = baixados = 0
    for indice, (impressao, url) in enumerate(pendentes, 1):
        conteudo = baixar(url)
        if not conteudo:
            falhas += 1
            if falhas <= 3 and verbose:
                print(f"[r2] nao consegui baixar: {url[:70]}")
            continue

        largura, altura = measure(conteudo)
        extensao = _extensao(conteudo)
        chave = f"creatives/{impressao}{extensao}"
        try:
            s3.put_object(
                Bucket=bucket, Key=chave, Body=conteudo,
                ContentType=mimetypes.types_map.get(extensao, "image/jpeg"),
                # Criativo nunca muda depois de salvo: cache longo evita pagar
                # banda de novo a cada visita.
                CacheControl="public, max-age=31536000, immutable",
            )
            enviadas[impressao] = {
                "key": chave, "w": largura, "h": altura, "bytes": len(conteudo),
            }
            baixados += 1
        except Exception as exc:  # noqa: BLE001
            falhas += 1
            if falhas <= 3 and verbose:
                print(f"[r2] upload falhou ({type(exc).__name__}): {chave}")
            if falhas >= 10:
                print("[r2] dez falhas seguidas — parando e salvando o progresso.")
                break
        if verbose and indice % 25 == 0:
            print(f"[r2]   {indice}/{len(pendentes)}")
            gravar_manifesto(raiz, enviadas)

    gravar_manifesto(raiz, enviadas)
    if verbose:
        peso = sum(v.get("bytes", 0) for v in enviadas.values() if isinstance(v, dict))
        print(f"[r2] {baixados} novos, {len(enviadas)} no bucket "
              f"({peso/1024/1024:.0f} MB)" + (f", {falhas} falharam" if falhas else ""))
    return {k: _info(base, v) for k, v in enviadas.items()}


def _extensao(conteudo: bytes) -> str:
    """Descobre o formato pelo cabecalho, sem confiar no nome da URL."""
    if conteudo[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return ".webp"
    if conteudo[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".jpg"


def _info(base: str, valor) -> dict:
    """O manifesto antigo guardava so a chave; o novo guarda as dimensoes."""
    if isinstance(valor, str):
        return {"url": f"{base}/{valor}", "w": 0, "h": 0, "bytes": 0}
    return {
        "url": f"{base}/{valor['key']}",
        "w": valor.get("w", 0),
        "h": valor.get("h", 0),
        "bytes": valor.get("bytes", 0),
    }
