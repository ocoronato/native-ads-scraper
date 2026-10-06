"""Modelo de um criativo capturado."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlparse

from .images import origin_image
from .niches import classify as classify_niche

# Campos na ordem em que saem no CSV.
CSV_FIELDS = [
    "captured_at",
    "first_seen",
    "last_seen",
    "days_seen",
    "times_seen",
    "streak",
    "best_streak",
    "span_days",
    "active",
    "seen_dates",
    "publisher",
    "device",
    "network",
    "headline",
    "advertiser",
    "niche",
    "click_url",
    "landing_domain",
    "utm_source",
    "utm_medium",
    "utm_content",
    "campaign_id",
    "click_params",
    "image_url",
    "image_file",
    "image_width",
    "image_height",
    "image_bytes",
    "source_url",
    "fingerprint",
]

# Portal linka pra irmao de rede e pra parceiro editorial, e esse link sai do
# dominio igual um anuncio sai — por isso "saiu do dominio" nao basta sozinho.
# Dominio grande de conteudo nunca e landing de native direct-response.
# Edite a vontade: e so uma lista.
EDITORIAL_DOMAINS = frozenset(
    {
        "bing.com", "msn.com", "microsoft.com", "yahoo.com", "aol.com",
        "usatoday.com", "allrecipes.com", "foxweather.com", "weather.com",
        "apnews.com", "reuters.com", "cbsnews.com", "nbcnews.com", "go.com",
        "abcnews.com", "businessinsider.com", "indiatimes.com", "people.com",
        "today.com", "eonline.com", "cnn.com", "bbc.com", "nytimes.com",
        "youtube.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    }
)

# Imagens que a rede serve quando o anuncio nao tem criativo — o Taboola usa um
# PNG de 12x12. Nao da pra reconhecer pela URL nem medir num background-image,
# entao a lista e por observacao. A checagem 5 do check.py acha candidatas
# novas: criativo de verdade pertence a um anunciante, placeholder atravessa
# varios, entao imagem compartilhada por 4+ dominios de destino e suspeita.
PLACEHOLDER_IMAGES = frozenset(
    {
        "https://cdn.taboola.com/libtrc/static/thumbnails/"
        "f539211219b796ffbb49949997c764f0.png",
    }
)

_WS = re.compile(r"\s+")
# O widget costuma colar o rotulo no nome do anunciante: "SPONSORED / Blinkist".
_LABEL_NOISE = re.compile(
    r"\b(sponsored|promoted|patrocinado|publicidade|an[uú]ncio|ad choices|logo)\b",
    re.IGNORECASE,
)


def _clean(text: str | None) -> str:
    """Normaliza espacos e corta lixo de widget."""
    if not text:
        return ""
    return _WS.sub(" ", text).strip()


def _clean_advertiser(text: str | None) -> str:
    """Tira o rotulo de publicidade e fica so com o nome da marca."""
    raw = _clean(text)
    if not raw:
        return ""
    # "Blinkist Magazine / Sponsored" -> pega o pedaco com conteudo de verdade.
    parts = [p.strip() for p in re.split(r"\s*[/|·•]\s*", raw) if p.strip()]
    for part in parts:
        stripped = _clean(_LABEL_NOISE.sub("", part)).strip(" -–—:,")
        if len(stripped) >= 2:
            return stripped[:80]
    return ""


@dataclass
class Creative:
    publisher: str
    device: str
    network: str
    headline: str
    click_url: str
    image_url: str
    source_url: str
    advertiser: str = ""
    image_file: str = ""
    image_width: int = 0
    image_height: int = 0
    image_bytes: int = 0
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        self.headline = _clean(self.headline)
        self.advertiser = _clean_advertiser(self.advertiser)

    @property
    def landing_domain(self) -> str:
        """Dominio final do anuncio, quando da pra ler direto da URL de clique."""
        try:
            host = urlparse(self.click_url).netloc.lower()
        except ValueError:
            return ""
        return host[4:] if host.startswith("www.") else host

    @property
    def click_params(self) -> dict[str, str]:
        """Todos os parametros da URL de clique, sem perder nenhum.

        E aqui que a rede escreve o que interessa: id de campanha, posicao do
        widget, as vezes ate o preco do leilao. Guardamos cru — cada rede usa
        um nome diferente, e o que hoje parece lixo amanha explica um teste.
        """
        try:
            pairs = parse_qsl(urlparse(self.click_url).query, keep_blank_values=True)
        except ValueError:
            return {}
        params: dict[str, str] = {}
        for key, value in pairs:
            params.setdefault(key, value)  # repetido: o primeiro vale
        return params

    def param(self, *names: str) -> str:
        """Busca um parametro ignorando maiusculas (campaignId vs campaignid)."""
        lowered = {k.lower(): v for k, v in self.click_params.items()}
        for name in names:
            value = lowered.get(name.lower())
            if value:
                return value
        return ""

    @property
    def registrable_domain(self) -> str:
        """'sports.yahoo.com' -> 'yahoo.com'. Suficiente pra bater na lista."""
        parts = self.landing_domain.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else self.landing_domain

    @property
    def fingerprint(self) -> str:
        """Chave de dedupe: mesma copy + mesma imagem de origem = mesmo criativo.

        A imagem tem que ser a ORIGEM, nao a URL do CDN. O mesmo criativo sai
        do Taboola em w_380, w_480, w_700 e w_880 conforme o tamanho do slot —
        usar a URL transformada criava um criativo por tamanho, enchia o viewer
        de cards iguais e, pior, quebrava o streak: visto ontem em w_700 e hoje
        em w_480 virava dois anuncios de streak 1 em vez de um de streak 2.

        Ignora publisher e device de proposito — se o mesmo criativo aparece no
        MSN e no Business Insider, e o mesmo anuncio, nao dois. O advertiser
        fica de fora porque cada widget escreve a marca de um jeito.
        """
        raw = f"{self.headline.lower()}|{origin_image(self.image_url)}"
        return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]

    def is_valid(self) -> bool:
        """Descarta o que claramente nao e um criativo aproveitavel."""
        if len(self.headline) < 15:
            return False
        # Botao de UI do proprio portal ("Share & Save —") passa pelo extrator
        # de rotulo. Headline de anuncio sempre tem frase, nao duas palavras.
        if len(re.findall(r"[^\W\d_]{2,}", self.headline, re.UNICODE)) < 3:
            return False
        if self.registrable_domain in EDITORIAL_DOMAINS:
            return False
        # Card de parceiro editorial nao tem criativo: o portal poe o logo da
        # marca no lugar. Anuncio nunca e servido de um caminho /logos/.
        # (O "/" importa: "Robinhood_New_Logo.png" e criativo de verdade.)
        if "/logo" in self.image_url.lower():
            return False
        # Criativo de native e sempre raster (jpg/png/webp). SVG nesse lugar e
        # icone ou placeholder de widget, nunca o anuncio.
        if self.image_url.lower().split("?")[0].endswith(".svg"):
            return False
        if origin_image(self.image_url) in PLACEHOLDER_IMAGES:
            return False
        if not self.image_url.startswith("http"):
            return False
        if not self.click_url.startswith("http"):
            return False
        # Widget as vezes devolve o proprio rotulo como se fosse item.
        junk = {"sponsored", "patrocinado", "ad", "publicidade", "promoted links"}
        return self.headline.lower() not in junk

    def to_row(self) -> dict:
        data = asdict(self)
        data["landing_domain"] = self.landing_domain
        data["niche"] = classify_niche(self.headline, self.landing_domain)
        data["fingerprint"] = self.fingerprint

        params = self.click_params
        data["click_params"] = json.dumps(params, ensure_ascii=False) if params else ""
        # Promovidos a coluna porque sao os que se filtra no dia a dia:
        # utm_content costuma trazer a posicao exata do widget.
        data["utm_source"] = self.param("utm_source")
        data["utm_medium"] = self.param("utm_medium")
        data["utm_content"] = self.param("utm_content")
        data["campaign_id"] = self.param("campaignId", "campaign_id", "campaign", "cid")

        return {key: data.get(key, "") for key in CSV_FIELDS}
