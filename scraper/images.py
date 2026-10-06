"""Achar a versao original da imagem, e medir o que foi baixado.

O widget nunca mostra o criativo inteiro: ele passa por um CDN de transformacao
que corta e recomprime — `q_50`, `w_420`, `resizefill_h100`. Mas essas URLs
carregam a origem dentro delas, ou no caminho (estilo Cloudinary) ou num
parametro. Extraindo a origem, salvamos o criativo como o anunciante subiu.
"""

from __future__ import annotations

import re
import struct
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

# Parametros que so servem pra encolher/piorar a imagem.
_SHRINK_PARAMS = {
    "w", "h", "width", "height", "q", "quality", "fit", "crop", "fm",
    "resize", "dpr", "size", "maxwidth", "maxheight", "m", "scale",
}

# Uma URL http dentro do caminho de outra URL (Cloudinary /fetch/, Yahoo, etc).
_EMBEDDED = re.compile(r"(https?(?:%3A|:)(?:%2F%2F|//).+)$", re.IGNORECASE)


def _strip_shrink_params(url: str) -> str:
    """Tira ?w=612&q=45 e afins, deixando a imagem no tamanho de origem."""
    parts = urlparse(url)
    if not parts.query:
        return url
    kept = {
        key: values
        for key, values in parse_qs(parts.query, keep_blank_values=True).items()
        if key.lower() not in _SHRINK_PARAMS
    }
    query = "&".join(f"{k}={v}" for k, vs in kept.items() for v in vs)
    return urlunparse(parts._replace(query=query))


def _embedded_url(url: str) -> str | None:
    """Pega a URL de origem escondida no caminho ou num parametro."""
    parts = urlparse(url)

    # Caso 1: veio num parametro, tipo shftr.adnxs.net/r?url=https%3A%2F%2F...
    for key, values in parse_qs(parts.query).items():
        if key.lower() in ("url", "u", "src", "image", "iu"):
            candidate = unquote(values[0])
            if candidate.startswith("http"):
                return candidate

    # Caso 2: veio no caminho. Vale so a partir do segundo segmento, senao
    # a propria URL casa consigo mesma.
    path = parts.path.lstrip("/")
    if "/" not in path:
        return None
    match = _EMBEDDED.search(path)
    if not match:
        return None
    candidate = unquote(match.group(1))
    # Cloudinary escreve "https://host" com uma barra so depois do esquema.
    candidate = re.sub(r"^(https?:)/(?!/)", r"\1//", candidate)
    return candidate if candidate.startswith("http") else None


def candidates(url: str, limit: int = 3) -> list[str]:
    """URLs a tentar, da melhor qualidade esperada para a original.

    A URL que veio do widget entra sempre por ultimo, como garantia: se a
    origem estiver protegida ou fora do ar, ainda salvamos alguma coisa.
    """
    found: list[str] = []

    def add(value: str | None) -> None:
        if value and value.startswith("http") and value not in found:
            found.append(value)

    origin = _embedded_url(url)
    if origin:
        add(_strip_shrink_params(origin))
        add(origin)
    else:
        stripped = _strip_shrink_params(url)
        if stripped != url:
            add(stripped)

    add(url)
    return found[:limit]


# ---------------------------------------------------------------------------
# Medicao. Sem Pillow: ler o cabecalho resolve para os formatos que aparecem.
# ---------------------------------------------------------------------------


def measure(data: bytes) -> tuple[int, int]:
    """Largura e altura lendo so o cabecalho. (0, 0) se nao reconhecer."""
    if len(data) < 24:
        return (0, 0)

    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return (width, height)

    if data[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", data[6:10])
        return (width, height)

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 ":
            width, height = struct.unpack("<HH", data[26:30])
            return (width & 0x3FFF, height & 0x3FFF)
        if chunk == b"VP8L":
            bits = struct.unpack("<I", data[21:25])[0]
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if chunk == b"VP8X":
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return (width, height)
        return (0, 0)

    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)

    return (0, 0)


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Anda pelos marcadores ate o SOF, que carrega as dimensoes."""
    index, total = 2, len(data)
    while index < total - 9:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        # SOF0..SOF15, pulando DHT/JPG/DAC que nao trazem tamanho.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return (width, height)
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        try:
            segment = struct.unpack(">H", data[index + 2 : index + 4])[0]
        except struct.error:
            return (0, 0)
        index += 2 + segment
    return (0, 0)


def origin_image(url: str) -> str:
    """URL da imagem como o anunciante a subiu, sem a transformacao do CDN.

    E a chave certa pra dizer se dois avistamentos sao o mesmo criativo: o
    widget pede a mesma imagem em varios tamanhos conforme o slot, e a URL
    transformada muda a cada um deles.
    """
    origem = _embedded_url(url) or url
    return _strip_shrink_params(origem).split("?")[0]
