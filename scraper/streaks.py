"""Ha quantos dias cada criativo esta no ar.

Em trafego direto, o sinal mais barato de que um anuncio esta dando lucro e
ele continuar rodando. Criativo ruim sai do ar em um ou dois dias; o que fica
uma semana esta pagando. Por isso guardamos cada dia em que vimos o criativo e
contamos a sequencia.

A sequencia conta **dias de coleta**, nao dias de calendario. Se voce nao rodar
o scraper no sabado, o anuncio nao "quebrou a streak" — voce e que nao olhou.
Contar calendario puniria o criativo pela sua folga, e o numero mentiria.
"""

from __future__ import annotations

from datetime import date


def today() -> str:
    """Data local. Rodar as 21h no Brasil nao pode virar o dia seguinte."""
    return date.today().isoformat()


def collection_days(rows: list[dict]) -> list[str]:
    """Os dias em que o scraper rodou, deduzidos do que ele viu."""
    days: set[str] = set()
    for row in rows:
        days.update(row.get("seen_dates") or [])
    return sorted(days)


def _run_length(positions: list[int]) -> int:
    """Quantos dias consecutivos terminando no ultimo avistamento."""
    streak = 1
    for index in range(len(positions) - 1, 0, -1):
        if positions[index] - positions[index - 1] != 1:
            break
        streak += 1
    return streak


def _longest_run(positions: list[int]) -> int:
    best = current = 1
    for previous, nxt in zip(positions, positions[1:]):
        current = current + 1 if nxt - previous == 1 else 1
        best = max(best, current)
    return best


def recompute(rows: list[dict]) -> None:
    """Recalcula os campos de streak de todas as linhas, no lugar."""
    # Migracao primeiro, dias de coleta depois: base antiga nao tem seen_dates,
    # e se a gente perguntasse pelos dias antes de preencher, a lista voltaria
    # vazia e todo criativo apareceria como "ja saiu do ar".
    for row in rows:
        counts = row.get("seen_counts")
        if not counts:
            # Base antiga so sabia em que dias viu, nao quantas vezes por dia.
            # Assume 1 por dia — subconta o passado, mas nao inventa numero.
            dates = row.get("seen_dates") or []
            if not dates:
                day = str(row.get("captured_at", ""))[:10]
                dates = [day] if day else []
            counts = {day: 1 for day in dates if day}
            row["seen_counts"] = counts
        # seen_dates passa a ser derivado do contador, nunca a fonte: se as
        # duas listas divergissem, o streak sairia de uma e o total da outra.
        row["seen_dates"] = sorted(counts)

    days = collection_days(rows)
    position_of = {day: index for index, day in enumerate(days)}
    last_run = days[-1] if days else ""

    for row in rows:
        counts = {d: int(n) for d, n in (row.get("seen_counts") or {}).items() if d}
        seen = sorted(counts)
        if not seen:
            # Sem data nenhuma nem em captured_at: trata como vista na ultima
            # coleta, que e o menos errado que da pra afirmar.
            seen = [last_run or today()]
            counts = {seen[0]: 1}
            row["seen_counts"] = counts
        row["seen_dates"] = seen
        # Quantas vezes o extrator topou com ele, somando todas as coletas.
        # Diferente de days_seen: 7 avistamentos em 2 dias significa que o
        # anuncio esta em varios publishers e varias posicoes ao mesmo tempo.
        row["times_seen"] = sum(counts.values())

        positions = sorted(position_of[d] for d in seen if d in position_of)
        if not positions:
            positions = [0]

        row["first_seen"] = seen[0]
        row["last_seen"] = seen[-1]
        row["days_seen"] = len(seen)
        row["streak"] = _run_length(positions)
        row["best_streak"] = _longest_run(positions)
        # Quantos dias de calendario a linha cobre. Se voce ficar uma semana
        # sem rodar, um criativo visto antes e depois marca streak 2 — correto
        # pela regra, mas span_days denuncia o buraco. Streak alto com span
        # muito maior que days_seen quer dizer "voce olhou pouco", nao
        # "o anuncio rodou sem parar".
        row["span_days"] = (
            date.fromisoformat(seen[-1]) - date.fromisoformat(seen[0])
        ).days + 1
        # "Ainda no ar": apareceu na coleta mais recente que voce fez.
        row["active"] = seen[-1] == last_run


def to_csv_value(value: object) -> object:
    """seen_dates vira '2026-09-21;2026-09-22' — o Excel le, o JSON mantem lista."""
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    if isinstance(value, bool):
        return "sim" if value else "nao"
    return value
