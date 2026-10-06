"""Pergunta as credenciais do R2 e grava o r2.config.json.

Rode no SEU terminal, nao por aqui — assim o segredo nao passa por chat nem
por log de ferramenta. O arquivo gerado esta no .gitignore e nao entra em
repositorio nenhum.

    .venv\\Scripts\\python configurar_r2.py
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESTINO = ROOT / "r2.config.json"


def perguntar(rotulo: str, ajuda: str, atual: str = "", secreto: bool = False) -> str:
    sufixo = f" [{atual[:6]}…]" if atual else ""
    print(f"\n{rotulo}{sufixo}")
    print(f"  {ajuda}")
    # Segredo nao aparece na tela nem fica no historico do terminal.
    valor = (getpass.getpass("  > ") if secreto else input("  > ")).strip()
    return valor or atual


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    atual: dict = {}
    if DESTINO.exists():
        try:
            atual = json.loads(DESTINO.read_text(encoding="utf-8"))
            print(f"[info] {DESTINO.name} ja existe — Enter mantem o valor atual.")
        except json.JSONDecodeError:
            pass

    print("=" * 62)
    print("Configuracao do Cloudflare R2")
    print("=" * 62)

    config = {
        "account_id": perguntar(
            "Account ID",
            "Painel da Cloudflare: e o trecho depois de dash.cloudflare.com/",
            atual.get("account_id", ""),
        ),
        "access_key_id": perguntar(
            "Access Key ID",
            "R2 > Manage API Tokens > o token que voce criou",
            atual.get("access_key_id", ""),
        ),
        "secret_access_key": perguntar(
            "Secret Access Key",
            "aparece uma vez so, na criacao do token (nao vai aparecer na tela)",
            atual.get("secret_access_key", ""),
            secreto=True,
        ),
        "bucket": perguntar(
            "Nome do bucket",
            "o que voce criou no R2",
            atual.get("bucket", "native-ads"),
        ),
        "public_base": perguntar(
            "URL publica",
            "bucket > Settings > Public access > R2.dev subdomain",
            atual.get("public_base", ""),
        ).rstrip("/"),
    }

    faltando = [k for k, v in config.items() if not v]
    if faltando:
        print(f"\n[erro] faltou preencher: {', '.join(faltando)}")
        return 1

    DESTINO.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"\n[ok] gravado em {DESTINO}")
    print("     esta no .gitignore — nao entra em repositorio")

    print("\nTestando a conexao...")
    try:
        sys.path.insert(0, str(ROOT))
        from scraper.r2 import carregar_config, cliente

        s3 = cliente(carregar_config(ROOT))
        s3.head_bucket(Bucket=config["bucket"])
        print(f"[ok] bucket '{config['bucket']}' acessivel")
        print("\nAgora rode:  .venv\\Scripts\\python publish.py")
    except Exception as exc:  # noqa: BLE001
        print(f"[erro] nao consegui acessar o bucket: {type(exc).__name__}: {exc}")
        print("       confira o Account ID, o token e o nome do bucket.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
