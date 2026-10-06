"""Publica o visualizador e os dados num repositorio privado.

O site hospedado le `data/creatives.json` do proprio repositorio. As imagens
NAO sobem: sao 1,3 GB, nao cabem num repo e nao precisam estar la — cada
criativo guarda a URL original do CDN, e o viewer usa essa quando nao encontra
arquivo local. A copia em alta resolucao continua so na sua maquina.

    .venv/Scripts/python publish.py              # sincroniza e empurra
    .venv/Scripts/python publish.py --dry-run    # mostra o que faria
    .venv/Scripts/python publish.py --init       # cria o repo privado
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT / "site"
REPO_PADRAO = "native-ads-radar"


def rodar(*args: str, cwd: Path = SITE, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=check,
    )


def montar_site(min_dias: int = 3) -> dict:
    """Copia o viewer e grava a versao dos dados que o site vai servir."""
    SITE.mkdir(exist_ok=True)
    (SITE / "data").mkdir(exist_ok=True)

    # O viewer vira index.html, sem nenhuma alteracao de codigo.
    shutil.copy(ROOT / "viewer.html", SITE / "index.html")

    rows = json.loads((DATA / "creatives.json").read_text(encoding="utf-8"))

    # Imagem em resolucao cheia vive no R2, nao no repositorio: 900 KB por
    # criativo e ~150 novos por dia dariam uns 4 GB por mes de repo.
    urls = {}
    try:
        from scraper.r2 import R2Indisponivel, enviar
        try:
            urls = enviar(ROOT, rows, min_dias=min_dias)
        except R2Indisponivel as motivo:
            print(f"[aviso] R2 nao configurado ({motivo})")
            print("        o site vai usar as URLs do CDN, que expiram com o tempo.")
    except ImportError:
        pass

    from scraper.images import origin_image

    for row in rows:
        # image_file vazio faz o viewer usar image_url direto.
        row["image_file"] = ""
        # A URL que o widget serve e a versao recortada do slot — uns 21 KB.
        # Ela carrega a origem dentro dela, e a origem tem cerca de 1 MB: 50x
        # mais qualidade pelo mesmo custo, que e zero. Guardamos a transformada
        # como reserva, pra imagem nao sumir se a origem der 404.
        transformada = row["image_url"]
        origem = origin_image(transformada)
        no_r2 = urls.get(row["fingerprint"])
        if no_r2:
            # Subiu pro R2: ali e o arquivo original mesmo, sem recompressao.
            row["image_url"] = no_r2["url"]
            # As dimensoes so sao conhecidas no momento do upload, porque e la
            # que a imagem e baixada. Guardamos pra base local tambem.
            if no_r2.get("w"):
                row["image_width"] = no_r2["w"]
                row["image_height"] = no_r2["h"]
                row["image_bytes"] = no_r2["bytes"]
        elif origem != transformada:
            row["image_url"] = origem
        row["image_fallback"] = transformada if transformada != row["image_url"] else ""
    (SITE / "data" / "creatives.json").write_text(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    dias = sorted({d for r in rows for d in (r.get("seen_dates") or [])})
    (SITE / ".gitignore").write_text("*.pyc\n__pycache__/\n", encoding="utf-8")
    (SITE / "README.md").write_text(
        "# Native Ads Radar\n\n"
        "Criativos de ad nativo coletados dos publishers de escala.\n"
        f"Atualizado automaticamente ao fim de cada coleta.\n\n"
        f"- {len(rows)} criativos\n"
        f"- {len(dias)} coletas ({dias[0]} a {dias[-1]})\n\n"
        "As imagens vem do CDN original da rede, nao deste repositorio.\n",
        encoding="utf-8",
    )
    # O que o R2 descobriu (largura, altura, peso) volta pra base local, que
    # e a fonte da verdade — senao essa informacao so existiria no site.
    if urls:
        locais = json.loads((DATA / "creatives.json").read_text(encoding="utf-8"))
        mudou_algo = False
        for linha in locais:
            info = urls.get(linha["fingerprint"])
            if info and info.get("w") and not linha.get("image_width"):
                linha["image_width"] = info["w"]
                linha["image_height"] = info["h"]
                linha["image_bytes"] = info["bytes"]
                mudou_algo = True
        if mudou_algo:
            (DATA / "creatives.json").write_text(
                json.dumps(locais, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    tamanho = sum(f.stat().st_size for f in (SITE / "data").rglob("*.*")) / 1024 / 1024
    return {"criativos": len(rows), "coletas": len(dias), "mb": tamanho}


def criar_repo(nome: str) -> int:
    """Cria o repositorio privado e faz o primeiro push."""
    if (SITE / ".git").exists():
        print("[info] o site ja e um repositorio git")
        return 0
    resumo = montar_site()
    rodar("git", "init", "-b", "main")
    # Identidade so neste repositorio: nao mexemos na config global da maquina.
    # O endereco noreply do GitHub evita expor o e-mail real no historico.
    usuario = rodar("gh", "api", "user", "-q", ".login", cwd=ROOT, check=False).stdout.strip()
    if usuario:
        rodar("git", "config", "user.name", usuario)
        rodar("git", "config", "user.email", f"{usuario}@users.noreply.github.com")
    rodar("git", "add", "-A")
    rodar("git", "commit", "-m",
          "Primeira publicacao do radar de criativos\n\n"
          "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>")
    proc = rodar("gh", "repo", "create", nome, "--private", "--source", ".",
                 "--push", check=False)
    if proc.returncode != 0:
        print("[erro] gh repo create falhou:\n" + (proc.stderr or proc.stdout))
        return 1
    print(f"[ok] repositorio privado criado e enviado ({resumo['criativos']} criativos)")
    url = rodar("gh", "repo", "view", "--json", "url", "-q", ".url", check=False)
    print(f"[ok] {url.stdout.strip()}")
    return 0


def publicar(dry_run: bool = False, min_dias: int = 3) -> int:
    if not (SITE / ".git").exists():
        print("[erro] o site ainda nao foi iniciado. Rode: publish.py --init")
        return 2

    resumo = montar_site(min_dias)
    mudou = rodar("git", "status", "--porcelain", check=False).stdout.strip()
    if not mudou:
        print("[info] nada mudou desde a ultima publicacao")
        return 0

    if dry_run:
        print(f"[dry-run] publicaria {resumo['criativos']} criativos "
              f"({resumo['mb']:.1f} MB)")
        print(mudou[:400])
        return 0

    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    rodar("git", "add", "-A")
    rodar("git", "commit", "-m",
          f"Coleta de {agora}: {resumo['criativos']} criativos, "
          f"{resumo['coletas']} dias")
    proc = rodar("git", "push", check=False)
    if proc.returncode != 0:
        print("[erro] push falhou:\n" + (proc.stderr or proc.stdout))
        return 1
    print(f"[ok] publicado: {resumo['criativos']} criativos ({resumo['mb']:.1f} MB)")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--init", action="store_true", help="cria o repositorio privado")
    parser.add_argument("--nome", default=REPO_PADRAO, help="nome do repositorio")
    parser.add_argument("--dry-run", action="store_true", help="mostra o que faria")
    parser.add_argument(
        "--min-dias",
        type=int,
        default=3,
        help="so sobe pro R2 criativo com esse tanto de dias no ar (padrao 3)",
    )
    args = parser.parse_args()

    if not (DATA / "creatives.json").exists():
        print("[erro] nao existe data/creatives.json — rode uma coleta antes.")
        return 2
    return criar_repo(args.nome) if args.init else publicar(args.dry_run, args.min_dias)


if __name__ == "__main__":
    raise SystemExit(main())
