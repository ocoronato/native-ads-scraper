"""Rebaixa as imagens ja coletadas, agora na melhor qualidade disponivel.

Os criativos antigos foram salvos com o thumbnail do widget. Este script passa
a mesma URL pelo extrator de origem e regrava o arquivo em resolucao cheia,
atualizando largura/altura/bytes no JSON e no CSV.

    .venv/Scripts/python upgrade_images.py            # tudo
    .venv/Scripts/python upgrade_images.py --limit 20 # so os 20 primeiros
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

from scraper.browser import BrowserSession
from scraper.images import measure
from scraper.models import CSV_FIELDS, Creative
from scraper.storage import CreativeStore

ROOT = Path(__file__).resolve().parent


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    store = CreativeStore(args.data)
    rows = store.rows[: args.limit] if args.limit else store.rows
    if not rows:
        print("nada pra atualizar.")
        return 1

    backup = args.data / "creatives.before-upgrade.json"
    if not backup.exists():
        shutil.copy(args.data / "creatives.json", backup)
        print(f"backup: {backup.name}")

    antes_px = depois_px = 0
    melhorou = igual = falhou = mantidos = 0

    with BrowserSession("desktop", headless=True) as session:
        for index, row in enumerate(rows, 1):
            velho = args.data / row["image_file"] if row.get("image_file") else None
            largura_velha = altura_velha = 0
            if velho and velho.exists():
                largura_velha, altura_velha = measure(velho.read_bytes())

            creative = Creative(
                publisher=row["publisher"], device=row["device"], network=row["network"],
                headline=row["headline"], click_url=row["click_url"],
                image_url=row["image_url"], advertiser=row["advertiser"],
                source_url=row["source_url"],
            )
            path, width, height, size = store.download_image(
                session.context.request, creative
            )
            if not path:
                # Duas coisas bem diferentes: a linha nunca teve criativo
                # baixavel (o widget serve um placeholder 12x12), ou tinha e o
                # refetch falhou agora — nesse caso o arquivo antigo continua la.
                if velho and velho.exists():
                    mantidos += 1
                    print(f"  {index:>4}/{len(rows)}  refetch falhou, mantido o antigo"
                          f"  {row['headline'][:38]}")
                else:
                    falhou += 1
                continue

            row.update(
                image_file=path, image_width=width, image_height=height, image_bytes=size
            )
            antes_px += largura_velha * altura_velha
            depois_px += width * height

            if width * height > largura_velha * altura_velha:
                melhorou += 1
                print(
                    f"  {index:>4}/{len(rows)}  {largura_velha}x{altura_velha}"
                    f" -> {width}x{height}   {row['headline'][:42]}"
                )
            else:
                igual += 1

    _flush(store, args.data)
    print(f"\nmelhoraram: {melhorou}  |  ja estavam no maximo: {igual}")
    print(f"mantido o arquivo antigo: {mantidos}  |  sem criativo baixavel: {falhou}")
    if antes_px:
        print(f"area total em pixels: {antes_px/1e6:.1f} MP -> {depois_px/1e6:.1f} MP"
              f"  ({depois_px/antes_px:.1f}x)")
    return 0


def _flush(store: CreativeStore, data: Path) -> None:
    (data / "creatives.json").write_text(
        json.dumps(store.rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (data / "creatives.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(store.rows)


if __name__ == "__main__":
    raise SystemExit(main())
