"""Separa os criativos que voltaram — os que passaram de um dia no ar.

Um anuncio visto uma vez so pode ser teste que morreu no mesmo dia. O que
reaparece numa coleta seguinte esta sendo mantido no ar, e manter custa
dinheiro: por isso essa e a lista que interessa olhar.

    .venv/Scripts/python winners.py                # 2+ dias, gera data/winners.csv
    .venv/Scripts/python winners.py --min-days 5   # so os que emendaram 5 coletas
    .venv/Scripts/python winners.py --ativos       # e que ainda estavam no ar na ultima
    .venv/Scripts/python winners.py --quiet        # sem a tabela na tela
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from scraper.models import CSV_FIELDS
from scraper.streaks import to_csv_value

ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--min-days",
        type=int,
        default=2,
        help="minimo de coletas distintas em que o criativo apareceu (padrao 2)",
    )
    parser.add_argument(
        "--min-times",
        type=int,
        default=0,
        help="minimo de avistamentos no total (volume, nao persistencia)",
    )
    parser.add_argument(
        "--niche",
        default="",
        help="so um nicho, ex: memoria-cognicao (veja niches.py --lista)",
    )
    parser.add_argument(
        "--ativos",
        action="store_true",
        help="so os que apareceram tambem na coleta mais recente",
    )
    parser.add_argument("--out", type=Path, default=None, help="caminho do CSV de saida")
    parser.add_argument("--quiet", action="store_true", help="nao imprime a tabela")
    return parser.parse_args()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()

    origem = args.data / "creatives.json"
    if not origem.exists():
        print(f"[erro] nao achei {origem}", file=sys.stderr)
        return 2

    rows = json.loads(origem.read_text(encoding="utf-8"))
    dias_de_coleta = sorted({d for r in rows for d in (r.get("seen_dates") or [])})

    escolhidos = [r for r in rows if (r.get("days_seen") or 1) >= args.min_days]
    if args.min_times:
        escolhidos = [r for r in escolhidos if (r.get("times_seen") or 1) >= args.min_times]
    if args.niche:
        escolhidos = [r for r in escolhidos if r.get("niche") == args.niche]
    if args.ativos:
        escolhidos = [r for r in escolhidos if r.get("active")]
    escolhidos.sort(
        key=lambda r: (r.get("days_seen", 0), r.get("times_seen", 0)), reverse=True
    )

    destino = args.out or (args.data / "winners.csv")
    with destino.open("w", newline="", encoding="utf-8-sig") as handle:
        campos = CSV_FIELDS + ["publishers"]
        writer = csv.DictWriter(handle, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            {key: to_csv_value(row.get(key, "")) for key in campos}
            for row in escolhidos
        )

    print(f"coletas ja feitas : {len(dias_de_coleta)} ({', '.join(dias_de_coleta[-5:])})")
    print(f"criativos na base : {len(rows)}")
    print(f"com {args.min_days}+ dias      : {len(escolhidos)}"
          + ("  (so os ativos)" if args.ativos else ""))
    print(f"gravado em        : {destino}")

    if len(dias_de_coleta) < 2:
        print(
            "\n[aviso] so existe uma coleta ate agora, entao ninguem pode ter mais"
            "\n        de um dia. Rode de novo amanha e a lista comeca a encher."
        )
    elif not args.quiet and escolhidos:
        print(f"\n{'dias':>4} {'vezes':>6} {'span':>4}  {'destino':<26} headline")
        print("-" * 96)
        for row in escolhidos[:30]:
            marca = "" if row.get("active") else "  (ja saiu)"
            print(
                f"{row.get('days_seen', 0):>4} {row.get('times_seen', 0):>6}"
                f" {row.get('span_days', 0):>4}  {str(row.get('landing_domain'))[:26]:<26}"
                f" {str(row.get('headline'))[:44]}{marca}"
            )
        if len(escolhidos) > 30:
            print(f"... e mais {len(escolhidos) - 30} no CSV")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
