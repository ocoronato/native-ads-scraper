"""Persistencia: JSON como fonte da verdade, CSV pra olhar, imagens em disco.

O dedupe e por fingerprint (copy + advertiser + imagem), entao rodar todo dia
so acrescenta o que e novo — o historico vai engordando sem repetir criativo.
"""

from __future__ import annotations

import csv
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError

from .images import candidates, measure
from .models import CSV_FIELDS, Creative
from .streaks import recompute, to_csv_value, today

_SAFE = re.compile(r"[^a-z0-9._-]+")


def _slug(text: str) -> str:
    return _SAFE.sub("-", text.lower()).strip("-") or "sem-nome"


class CreativeStore:
    def __init__(self, root: Path):
        self.root = root
        self.images_dir = root / "images"
        self.json_path = root / "creatives.json"
        self.csv_path = root / "creatives.csv"
        self.root.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        self.rows: list[dict] = self._load()
        self.index: dict[str, dict] = {row["fingerprint"]: row for row in self.rows}
        self.added = 0
        self.repeated_today = 0  # mesmo criativo, mesma coleta: nao diz nada
        self.returning = 0  # visto de novo num outro dia: streak cresceu

    def _load(self) -> list[dict]:
        if not self.json_path.exists():
            return []
        try:
            data = json.loads(self.json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [row for row in data if isinstance(row, dict) and row.get("fingerprint")]

    def add(self, creative: Creative) -> bool:
        """Registra o avistamento. Devolve True so quando a linha e inedita.

        Reencontrar um criativo nao e mais "pular duplicata": e a informacao
        mais valiosa que este raspador produz. Anuncio que volta dia apos dia
        esta pagando — entao aqui a gente carimba mais um dia na linha que ja
        existe, e o streak sai disso.
        """
        if not creative.is_valid():
            return False

        day = today()
        existing = self.index.get(creative.fingerprint)
        if existing is not None:
            counts = dict(existing.get("seen_counts") or {})
            ja_visto_hoje = day in counts
            # Conta todo avistamento, inclusive os do mesmo dia: achar o mesmo
            # anuncio em cinco paginas diferentes nao e ruido, e o anunciante
            # comprando volume em varios slots ao mesmo tempo.
            counts[day] = counts.get(day, 0) + 1
            existing["seen_counts"] = counts
            existing["seen_dates"] = sorted(counts)
            if ja_visto_hoje:
                self.repeated_today += 1
            else:
                self.returning += 1
            return False

        row = creative.to_row()
        row["seen_counts"] = {day: 1}
        row["seen_dates"] = [day]
        self.rows.append(row)
        self.index[creative.fingerprint] = row
        self.added += 1
        return True

    def _fetch(self, api_request, url: str) -> tuple[bytes, str] | None:
        """Baixa uma URL pelo contexto do browser (leva cookie e referer certos)."""
        try:
            response = api_request.get(url, timeout=25_000)
            if not response.ok:
                return None
            body = response.body()
        except (PlaywrightError, OSError):
            return None
        if len(body) < 1024:  # tracker de 1x1 disfarcado de imagem
            return None
        return body, response.headers.get("content-type", "")

    def download_image(self, api_request, creative: Creative) -> tuple[str, int, int, int]:
        """Salva a melhor versao da imagem. Devolve (caminho, largura, altura, bytes).

        Tenta primeiro a origem extraida da URL do CDN e fica com a variante de
        maior area em pixels — nao a de maior arquivo, senao um PNG pequeno e
        pesado ganharia de um JPEG grande.
        """
        folder = self.images_dir / _slug(creative.publisher)
        folder.mkdir(parents=True, exist_ok=True)

        best: tuple[int, bytes, str, str] | None = None  # (pixels, body, ctype, url)
        for url in candidates(creative.image_url):
            fetched = self._fetch(api_request, url)
            if not fetched:
                continue
            body, ctype = fetched
            width, height = measure(body)
            pixels = width * height or len(body)  # formato exotico: cai pro tamanho
            if best is None or pixels > best[0]:
                best = (pixels, body, ctype, url)

        if best is None:
            return "", 0, 0, 0

        _, body, ctype, url = best
        width, height = measure(body)

        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
            guessed = mimetypes.guess_extension((ctype.split(";")[0] or "").strip())
            ext = guessed if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".jpg"

        path = folder / f"{creative.fingerprint}{ext}"
        path.write_bytes(body)
        relative = str(path.relative_to(self.root)).replace("\\", "/")
        return relative, width, height, len(body)

    def flush(self) -> None:
        """Recalcula os streaks, grava o JSON e reescreve o CSV a partir dele."""
        recompute(self.rows)
        self.json_path.write_text(
            json.dumps(self.rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with self.csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            # Lista e booleano nao cabem numa celula: viram texto legivel.
            writer.writerows(
                {key: to_csv_value(row.get(key, "")) for key in CSV_FIELDS}
                for row in self.rows
            )
