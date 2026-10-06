"""Diagnostico de uma URL: mostra o que cada estrategia acha, sem filtrar nada.

    .venv/Scripts/python diagnose.py https://www.yahoo.com/ --device desktop

Serve pra descobrir por que um publisher esta rendendo zero: se o extrator nao
ve nada, se ve mas classifica como organico, ou se a API nao foi interceptada.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from scraper.browser import BrowserSession, harvest_url


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--device", choices=["desktop", "mobile"], default="desktop")
    parser.add_argument("--scrolls", type=int, default=10)
    parser.add_argument("--headful", action="store_true")
    args = parser.parse_args()

    with BrowserSession(args.device, headless=not args.headful) as session:
        # sponsored_only=False de proposito: queremos ver tudo que o extrator ve.
        items, status, links = harvest_url(
            session.context,
            args.url,
            scrolls=args.scrolls,
            pause_ms=1200,
            sponsored_only=False,
            collect_links=5,
        )

    paid = [i for i in items if i.get("paid") or i.get("sponsored")]
    print(f"\nstatus      : {status}")
    print(f"itens totais: {len(items)}  |  marcados como pagos: {len(paid)}")
    print(f"por network : {dict(Counter(i.get('network', '?') for i in items))}")

    print("\n--- links de materia que ele escolheria ---")
    for link in links:
        print("   ", link)

    print("\n--- 15 primeiros itens (P = pago) ---")
    for item in items[:15]:
        flag = "P" if (item.get("paid") or item.get("sponsored")) else " "
        print(f" [{flag}] {item.get('network', '?'):<12} {item.get('headline', '')[:62]}")
        print(f"      -> {item.get('click_url', '')[:88]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
