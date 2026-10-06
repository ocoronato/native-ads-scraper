"""CLI: varre os publishers e guarda os criativos.

    python -m scraper.run                          # tudo, desktop + mobile
    python -m scraper.run --only yahoo,msn         # so alguns
    python -m scraper.run --device mobile --headful
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

from .browser import BrowserSession, harvest_url, limpar_abas_nossas, polite_pause
from .connect import MoreLogin, resolve_cdp
from .models import Creative
from .storage import CreativeStore

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Publisher:
    name: str
    urls: list[str]
    devices: list[str]


def load_publishers(path: Path) -> list[Publisher]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    publishers = []
    for entry in raw:
        urls = entry.get("urls") or ([entry["url"]] if entry.get("url") else [])
        if not entry.get("name") or not urls:
            continue
        publishers.append(
            Publisher(
                name=entry["name"],
                urls=urls,
                devices=entry.get("devices") or ["desktop"],
            )
        )
    return publishers


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scraper",
        description="Raspa criativos de ad nativo dos publishers de escala.",
    )
    parser.add_argument("--config", type=Path, default=ROOT / "publishers.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--device", choices=["desktop", "mobile", "both"], default="both"
    )
    parser.add_argument("--only", default="", help="lista separada por virgula: yahoo,msn")
    parser.add_argument("--scrolls", type=int, default=9, help="quantidade de rolagens por pagina")
    parser.add_argument("--pause", type=int, default=1200, help="ms de espera entre rolagens")
    parser.add_argument("--max-urls", type=int, default=0, help="limita URLs por publisher (0 = todas)")
    parser.add_argument(
        "--articles",
        type=int,
        default=3,
        help="materias visitadas a partir de cada pagina (e onde o widget nativo vive)",
    )
    parser.add_argument("--headful", action="store_true", help="mostra o browser rodando")
    parser.add_argument(
        "--include-organic",
        action="store_true",
        help="tambem guarda recomendacao nao paga do widget",
    )
    parser.add_argument("--locale", default="en-US")
    parser.add_argument(
        "--timezone",
        default="",
        help="fuso do navegador, ex: America/New_York (coerencia com proxy US)",
    )

    geo = parser.add_argument_group("geografia — de onde os anuncios sao servidos")
    geo.add_argument(
        "--cdp",
        default="",
        help="pluga num navegador ja aberto (MoreLogin/AdsPower): 'auto', uma porta, ou a URL",
    )
    geo.add_argument(
        "--proxy",
        default="",
        help="proxy pro Chromium proprio: http://user:senha@host:porta",
    )
    geo.add_argument(
        "--morelogin",
        default="",
        help="inicia um perfil do MoreLogin pelo id ou nome e raspa dentro dele",
    )
    geo.add_argument(
        "--keep-open",
        action="store_true",
        help="com --morelogin, deixa o perfil aberto no fim em vez de fechar",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="nao sincroniza com o site hospedado no fim da coleta",
    )

    geo.add_argument(
        "--device-label",
        default="desktop",
        help="com --cdp, so rotula as linhas: quem define o device e o perfil",
    )
    return parser.parse_args(argv)


def parse_proxy(raw: str) -> dict | None:
    """Converte 'http://user:senha@host:porta' no formato do Playwright."""
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if not parsed.hostname:
        raise ValueError(f"proxy invalido: {raw}")
    proxy = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 8080}"}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


def _absorb(store, session, args, items, publisher: str, device: str, url: str) -> int:
    """Converte itens brutos em criativos, guarda os ineditos e baixa a imagem."""
    new_count = 0
    for item in items:
        creative = Creative(
            publisher=publisher,
            device=device,
            network=item.get("network", "other"),
            headline=item.get("headline", ""),
            click_url=item.get("click_url", ""),
            image_url=item.get("image_url", ""),
            advertiser=item.get("advertiser", ""),
            source_url=url,
        )
        if not store.add(creative):
            continue
        new_count += 1
        # A imagem NAO e baixada aqui. A maioria dos criativos aparece uma vez
        # e some: baixar todos enchia o disco de 1,3 GB de material descartavel.
        # Quem sobrevive 3 coletas e buscado e arquivado pelo publish.py, e
        # nesse momento a URL ainda esta viva porque ele acabou de ser visto.
    return new_count


def _sweep(args, publishers, devices, store, per_publisher, proxy, cdp_url) -> int:
    """Passa por cada device e cada publisher. Devolve quantas paginas falharam."""
    falhas_de_pagina = 0
    for device in devices:
        targets = publishers if cdp_url else [p for p in publishers if device in p.devices]
        if not targets:
            continue
        print(f"\n=== {device.upper()} — {len(targets)} publisher(s) ===")

        with BrowserSession(
            device if device in ("desktop", "mobile") else "desktop",
            headless=not args.headful,
            locale=args.locale,
            timezone=args.timezone or None,
            proxy=proxy,
            cdp_url=cdp_url,
        ) as session:
            # Num perfil emprestado, aba nossa de rodada anterior pode ter
            # sobrado: limpa antes de abrir mais.
            if cdp_url:
                hosts = {urlparse(u).netloc.lower().removeprefix("www.")
                         for p in publishers for u in p.urls}
                limpar_abas_nossas(session.context, hosts)

            for publisher in targets:
                seeds = publisher.urls[: args.max_urls] if args.max_urls else publisher.urls
                # Fila: (url, quantas materias colher a partir dela).
                queue: list[tuple[str, int]] = [(url, args.articles) for url in seeds]
                visited: set[str] = set()
                seguidas = 0  # falhas consecutivas de navegador

                while queue:
                    url, want_links = queue.pop(0)
                    if url in visited:
                        continue
                    visited.add(url)

                    try:
                        items, status, links = harvest_url(
                            session.context,
                            url,
                            scrolls=args.scrolls,
                            pause_ms=args.pause,
                            sponsored_only=not args.include_organic,
                            collect_links=want_links,
                        )
                        # Pagina que nao abre volta como lista vazia, nao como
                        # excecao — entao sem olhar o status o contador de
                        # falhas nunca dispara e uma coleta com o proxy morto
                        # termina "com sucesso" e zero resultado. Silencio nao
                        # e sucesso.
                        if status.startswith("falhou ao abrir"):
                            seguidas += 1
                            falhas_de_pagina += 1
                        else:
                            seguidas = 0
                    except Exception as exc:  # noqa: BLE001
                        # Nem abrir a aba deu: o navegador provavelmente caiu.
                        # Uma falha e azar; varias seguidas e o perfil que
                        # morreu, e insistir so queima tempo.
                        seguidas += 1
                        print(f"  !  {publisher.name:<16} falhou em {url}"
                              f"  ({type(exc).__name__})")
                        if seguidas >= 3:
                            print("  !  tres falhas seguidas — navegador ou proxy fora. "
                                  "Salvando o que ja foi coletado e encerrando.")
                            store.flush()
                            return falhas_de_pagina
                        continue
                    new_here = _absorb(store, session, args, items, publisher.name, device, url)
                    per_publisher[publisher.name] += new_here

                    if seguidas >= 3:
                        print(f"  !  {publisher.name:<16} tres paginas seguidas sem abrir"
                              f"  — proxy ou navegador fora do ar. Encerrando.")
                        store.flush()
                        return falhas_de_pagina

                    mark = " " if want_links else "  >"
                    print(f" {mark}{publisher.name:<16} {new_here:>3} novos   [{status}]  {url}")
                    store.flush()

                    # As materias entram na fila sem colher links (nao cavamos fundo).
                    queue.extend((link, 0) for link in links)
                    polite_pause(2.0)

    return falhas_de_pagina



def _publicar() -> None:
    """Empurra os dados novos pro site hospedado, se ele existir.

    Falha aqui nao pode derrubar a coleta: os criativos ja estao salvos
    em disco, e nao conseguir publicar e um problema de rede, nao de
    coleta. Avisa e segue.
    """
    publicador = ROOT / "publish.py"
    if not publicador.exists() or not (ROOT / "site" / ".git").exists():
        return
    print("\n  publicando no site...")
    try:
        proc = subprocess.run(
            [sys.executable, str(publicador)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
        for linha in (proc.stdout or "").strip().splitlines()[-2:]:
            print(f"  {linha}")
        if proc.returncode != 0:
            print(f"  [aviso] publicacao falhou: {(proc.stderr or '').strip()[-160:]}")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  [aviso] publicacao falhou: {type(exc).__name__}")


def run(args: argparse.Namespace) -> int:
    if not args.config.exists():
        print(f"[erro] config nao encontrada: {args.config}", file=sys.stderr)
        return 2

    publishers = load_publishers(args.config)
    wanted = {n.strip() for n in args.only.split(",") if n.strip()}
    if wanted:
        publishers = [p for p in publishers if p.name in wanted]
        missing = wanted - {p.name for p in publishers}
        if missing:
            print(f"[aviso] ignorando nomes desconhecidos: {', '.join(sorted(missing))}")
    if not publishers:
        print("[erro] nenhum publisher selecionado.", file=sys.stderr)
        return 2

    morelogin: MoreLogin | None = None
    started_env: str | None = None
    try:
        proxy = parse_proxy(args.proxy)
        if args.morelogin:
            morelogin = MoreLogin()
            profile = morelogin.resolve(args.morelogin)
            started_env = str(profile["id"])
            ip = (profile.get("proxy") or {}).get("proxyIp") or "sem proxy"
            print(f"[info] perfil '{profile.get('envName')}' (id {started_env}) — saida {ip}")
            cdp_url = morelogin.start(started_env)
            print(f"[info] perfil no ar, CDP em {cdp_url}")
        else:
            cdp_url = resolve_cdp(args.cdp) if args.cdp else None
    except (ValueError, RuntimeError) as exc:
        print(f"[erro] {exc}", file=sys.stderr)
        return 2

    if cdp_url:
        # Num navegador emprestado nao existe "rodar em desktop e mobile": o
        # perfil ja e um device so. Uma passada, rotulada com --device-label.
        devices = [args.device_label]
        if args.proxy:
            print("[aviso] --proxy ignorado: quem manda na saida e o perfil do navegador.")
    else:
        devices = ["desktop", "mobile"] if args.device == "both" else [args.device]

    store = CreativeStore(args.out)
    per_publisher: Counter[str] = Counter()
    started_with = len(store.rows)

    try:
        falhas_de_pagina = _sweep(args, publishers, devices, store, per_publisher, proxy, cdp_url)
    finally:
        if morelogin and started_env and not args.keep_open:
            morelogin.close(started_env)
            print(f"\n[info] perfil {started_env} fechado")

    store.flush()
    print("\n---------------- resumo ----------------")
    for name, count in per_publisher.most_common():
        print(f"  {name:<20} {count:>4} criativos novos")
    if falhas_de_pagina:
        print(f"\n  [aviso] {falhas_de_pagina} pagina(s) nao abriram")
    print(f"\n  criativos ineditos        : {store.added}")
    print(f"  reencontrados (streak +1) : {store.returning}")
    print(f"  repetidos na mesma coleta : {store.repeated_today}")
    print(f"  base total         : {started_with} -> {len(store.rows)}")
    print(f"\n  CSV     {store.csv_path}")
    print(f"  JSON    {store.json_path}")
    print(f"  imagens {store.images_dir}")

    if not args.no_publish:
        _publicar()
    # Coleta que nao achou nada E teve pagina falhando nao e sucesso:
    # devolver 0 aqui faria o driver marcar a rodada como boa.
    if falhas_de_pagina and not (store.added or store.returning):
        print("\n  [erro] nada coletado e paginas falhando — verifique o proxy do perfil.")
        return 1
    return 0


def main() -> int:
    # O console do Windows abre em cp1252 e engasga com acento/emdash das
    # headlines que a gente imprime no progresso.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    try:
        return run(parse_args())
    except KeyboardInterrupt:
        print("\n[interrompido]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
