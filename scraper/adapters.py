"""Duas formas de achar o criativo: pela API do widget e pelo DOM.

A primeira e a boa. Taboola, Outbrain e MSN montam o widget a partir de um
JSON que passa pela rede — interceptar esse JSON entrega headline, imagem,
advertiser e link de destino limpos, sem depender de classe de CSS que muda
toda semana. O DOM entra como rede de seguranca e cobre Yahoo/AOL, que montam
o ad nativo direto no HTML do stream.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

# Endpoints que devolvem recomendacao paga. Batemos por substring na URL.
AD_API_PATTERNS = (
    "taboola.com/1.0/json",
    "taboola.com/1.1/json",
    "taboola.com/1.2/json",
    "recommendations.get",
    "odb.outbrain.com/utils/get",
    "outbrain.com/utils/get",
    "arc.msn.com/v3/delivery",
    "arc.msn.com/v4/api/selection",
    "native.taboola.com",
    "trc.taboola.com",
    "trends.revcontent.com/api",
    "revcontent.com/rest",
    "servicer.mgid.com",
    "jsc.mgid.com",
)

# Hosts que so aparecem em link de anuncio — usado pra reconhecer um card pago.
AD_CLICK_HOSTS = (
    "trc.taboola.com",
    "taboola.com/click",
    "paid.outbrain.com",
    "outbrain.com/network/redir",
    "beap.gemini.yahoo.com",
    "ads.yahoo.com",
    "googleads.g.doubleclick.net",
    "adclick.g.doubleclick.net",
    "zemanta.com",
    "revcontent.com",
    "mgid.com",
)

_TITLE_KEYS = ("name", "content", "title", "headline", "shorttitle", "text")
_IMAGE_KEYS = ("thumbnail", "image", "thumbnailurl", "imageurl", "img", "picture")
_URL_KEYS = ("url", "clickurl", "click_url", "destinationurl", "targeturl", "link")
_BRAND_KEYS = ("branding", "source_name", "sourcename", "advertiser", "brand", "publisher")
_PAID_HINT_KEYS = ("disclosure", "is_paid", "ispaid", "sponsored")


def is_ad_api(url: str) -> bool:
    low = url.lower()
    return any(pattern in low for pattern in AD_API_PATTERNS)


def _lower_keys(obj: dict) -> dict:
    """Taboola manda minusculo, MSN manda CamelCase. Normalizamos."""
    return {str(k).lower(): v for k, v in obj.items()}


def _first(node: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = node.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _as_image_url(value: Any) -> str:
    """thumbnail vem como string, dict ou lista de dicts, conforme o fornecedor."""
    if isinstance(value, str):
        return value if value.startswith("http") else ""
    if isinstance(value, dict):
        url = value.get("url") or value.get("Url") or value.get("src")
        return url if isinstance(url, str) and url.startswith("http") else ""
    if isinstance(value, list) and value:
        return _as_image_url(value[0])
    return ""


def _walk(node: Any, depth: int = 0) -> Iterator[dict]:
    """Percorre o JSON inteiro procurando qualquer dict que possa ser um item."""
    if depth > 12:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, depth + 1)


def parse_ad_payload(body: str, sponsored_only: bool = True) -> list[dict]:
    """Extrai itens de anuncio de uma resposta de API de widget.

    Nao amarra em schema: varre o JSON e aceita todo no que tenha titulo,
    imagem e link ao mesmo tempo. Sobrevive a mudanca de formato.
    """
    body = body.strip()
    # Algumas respostas vem em JSONP: callback({...}).
    if body and not body.startswith(("{", "[")):
        start, end = body.find("("), body.rfind(")")
        if start == -1 or end <= start:
            return []
        body = body[start + 1 : end]

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return []

    items: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for raw in _walk(payload):
        node = _lower_keys(raw)
        title = _first(node, _TITLE_KEYS)
        if not isinstance(title, str) or len(title.strip()) < 12:
            continue
        image = _as_image_url(_first(node, _IMAGE_KEYS))
        if not image:
            continue
        url = _first(node, _URL_KEYS)
        if not isinstance(url, str) or not url.startswith("http"):
            continue

        origin = str(node.get("origin", "")).lower()
        paid = (
            origin == "sponsored"
            or any(node.get(k) for k in _PAID_HINT_KEYS)
            or any(host in url.lower() for host in AD_CLICK_HOSTS)
        )
        if sponsored_only and not paid:
            continue

        key = (title.strip().lower(), image.split("?")[0])
        if key in seen:
            continue
        seen.add(key)

        brand = _first(node, _BRAND_KEYS)
        items.append(
            {
                "headline": title,
                "image_url": image,
                "click_url": url,
                "advertiser": brand if isinstance(brand, str) else "",
                "sponsored": paid,
            }
        )

    return items


# Substring do host -> nome da rede. Ordem importa: o primeiro que bater vence.
NETWORK_BY_HOST = (
    ("taboola", "taboola"),
    ("outbrain", "outbrain"),
    ("revcontent", "revcontent"),
    ("mgid", "mgid"),
    ("zemanta", "zemanta"),
    ("doubleclick", "google-ads"),
    ("arc.msn", "msn-native"),
    ("msn.com", "msn-native"),
    ("gemini.yahoo", "yahoo-gemini"),
    ("yahoo", "yahoo-gemini"),
    ("aol", "yahoo-gemini"),
)


def network_of(url: str) -> str:
    low = url.lower()
    for needle, name in NETWORK_BY_HOST:
        if needle in low:
            return name
    return "other"


# ---------------------------------------------------------------------------
# Extrator de DOM. Roda dentro da pagina e dentro de cada iframe.
# ---------------------------------------------------------------------------

DOM_EXTRACTOR_JS = r"""
(adHosts) => {
  const out = [];
  const seen = new Set();

  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return ''; } };

  // MSN (e boa parte dos portais novos) monta o feed dentro de Shadow DOM, e
  // document.querySelectorAll nao atravessa shadow root. Sem furar isso, a
  // pagina parece ter um link so. Coletamos as raizes uma vez e reusamos.
  const ROOTS = (() => {
    const roots = [document];
    const walk = (root) => {
      let nodes;
      try { nodes = root.querySelectorAll('*'); } catch (e) { return; }
      for (const el of nodes) {
        if (el.shadowRoot) { roots.push(el.shadowRoot); walk(el.shadowRoot); }
      }
    };
    walk(document);
    return roots;
  })();

  const deepQuery = (selector) => {
    const found = [];
    for (const root of ROOTS) {
      try { found.push(...root.querySelectorAll(selector)); } catch (e) { /* seletor invalido */ }
    }
    return found;
  };

  const isAdLink = (href) => !!href && adHosts.some(h => href.toLowerCase().includes(h));

  // mesma tabela host -> rede que o lado Python usa
  const NET_BY_HOST = [
    ['taboola', 'taboola'], ['outbrain', 'outbrain'], ['revcontent', 'revcontent'],
    ['mgid', 'mgid'], ['zemanta', 'zemanta'], ['doubleclick', 'google-ads'],
    ['gemini.yahoo', 'yahoo-gemini'], ['ads.yahoo', 'yahoo-gemini'],
  ];
  const netOf = (href) => {
    const h = (href || '').toLowerCase();
    for (const [needle, name] of NET_BY_HOST) if (h.includes(needle)) return name;
    return 'other';
  };

  const bgOf = (el) => {
    const raw = getComputedStyle(el).backgroundImage || '';
    const m = raw.match(/url\(["']?(.*?)["']?\)/);
    return (m && !m[1].startsWith('data:')) ? abs(m[1]) : '';
  };

  // Enquanto o criativo nao entra na viewport, a rede serve um placeholder no
  // src — o Taboola usa um PNG de 12x12. Quem sabe a imagem de verdade e o
  // atributo de lazy-load, entao ele vem primeiro. E se so houver src e ele ja
  // tiver carregado minusculo, e placeholder: melhor nao ter imagem do que
  // gravar uma que nao e o anuncio.
  const srcOf = (img) => {
    const lazy = img.getAttribute('data-src') || img.getAttribute('data-lazy-src')
              || img.getAttribute('data-original') || '';
    let src = lazy || img.currentSrc || img.getAttribute('src') || '';
    if ((!src || src.startsWith('data:')) && img.getAttribute('srcset')) {
      const parts = img.getAttribute('srcset').split(',').map(s => s.trim()).filter(Boolean);
      if (parts.length) src = parts[parts.length - 1].split(/\s+/)[0];
    }
    if (!src || src.startsWith('data:')) return '';
    if (/1x1|pixel|spacer|blank\./i.test(src)) return '';
    if (!lazy && img.naturalWidth > 0 && img.naturalWidth < 50) return '';
    return abs(src);
  };

  const imageOf = (root) => {
    for (const img of root.querySelectorAll('img')) {
      const found = srcOf(img);
      if (found) return found;
    }
    const own = bgOf(root);
    if (own) return own;
    for (const el of root.querySelectorAll('*')) {
      const b = bgOf(el);
      if (b) return b;
    }
    return '';
  };

  const headlineOf = (root, link) => {
    const preferred = root.querySelector(
      '.video-title, .ob-rec-text, [class*="title" i], [class*="headline" i], h1, h2, h3, h4'
    );
    const texts = [
      preferred && preferred.textContent,
      link && (link.getAttribute('title') || link.getAttribute('aria-label')),
      root.textContent
    ];
    for (const t of texts) {
      const clean = (t || '').replace(/\s+/g, ' ').trim();
      if (clean.length >= 12 && clean.length <= 260) return clean;
    }
    return '';
  };

  const brandOf = (root) => {
    const el = root.querySelector(
      '.branding, .ob-rec-source, [class*="brand" i], [class*="source" i], [class*="sponsor" i]'
    );
    return el ? (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80) : '';
  };

  const cardOf = (link) => {
    let el = link;
    for (let i = 0; i < 6 && el && el.parentElement; i++) {
      if (el.querySelector('img') || bgOf(el)) break;
      el = el.parentElement;
    }
    return el || link;
  };

  // O mesmo widget serve recomendacao paga e recomendacao editorial do proprio
  // portal. O que separa: anuncio sai do dominio do publisher — seja pelo
  // redirect da rede (trc.taboola.com...), seja direto pra landing do
  // anunciante, que e como o Taboola entrega hoje. Editorial aponta pra casa.
  // Sem esse corte, metade da colheita vira materia do proprio site.
  const isExternal = (href) => {
    try { return new URL(href).host !== location.host; } catch (e) { return false; }
  };

  const push = (root, link, network, paid) => {
    const href = abs(link.getAttribute('href') || '');
    if (!href.startsWith('http')) return;
    const headline = headlineOf(root, link);
    const image = imageOf(root);
    if (!headline || !image) return;
    const key = headline.toLowerCase() + '|' + image.split('?')[0];
    if (seen.has(key)) return;
    seen.add(key);
    out.push({
      headline,
      image_url: image,
      click_url: href,
      advertiser: brandOf(root),
      network,
      paid: paid === undefined ? (isAdLink(href) || isExternal(href)) : paid,
    });
  };

  // --- Estrategia 1: containers conhecidos de cada rede -------------------
  const WIDGETS = [
    ['taboola',      '.videoCube, .trc_spotlight_item, [class*="trc_rbox"] [class*="item"], [id^="taboola"] a[href]'],
    ['outbrain',     '.ob-dynamic-rec-container, .ob-rec-link, .ob-p, [class*="ob-widget"] a[href]'],
    ['yahoo-gemini', '[data-test-locator*="ad" i], [class*="stream-ad" i], [id^="stream-ad"], .ad-container'],
    ['msn-native',   '[aria-label="Ad"], [aria-label*="Advertisement" i], [data-t*="Ad" i]'],
  ];
  for (const [network, selector] of WIDGETS) {
    const nodes = deepQuery(selector);
    for (const node of nodes) {
      const link = node.matches('a[href]') ? node : node.querySelector('a[href]');
      if (link) push(node.closest('li, article, div') || node, link, network, undefined);
    }
  }

  // --- Estrategia 2: qualquer link que aponte pra host de clique de ad ----
  for (const link of deepQuery('a[href]')) {
    const href = link.getAttribute('href') || '';
    if (!isAdLink(href)) continue;
    push(cardOf(link), link, netOf(href), true);
  }

  // --- Estrategia 3: card com rotulo de publicidade ao lado --------------
  const LABEL = /^(sponsored|promoted|ad|advertisement|patrocinado|publicidade|anuncio|ad feedback)$/i;
  for (const el of deepQuery('span, div, a, p, button')) {
    const txt = (el.textContent || '').trim();
    if (txt.length > 20 || !LABEL.test(txt)) continue;
    let card = el;
    for (let i = 0; i < 5 && card && card.parentElement; i++) {
      card = card.parentElement;
      const link = card.querySelector('a[href]');
      if (link && card.querySelector('img')) {
        const href = link.getAttribute('href') || '';
        // O rotulo sozinho nao basta: "Sponsored" tambem encosta em card
        // editorial e em bloco de servico do proprio portal. Exigimos que o
        // clique saia do dominio, igual as outras estrategias.
        push(card, link, isAdLink(href) ? netOf(href) : 'labelled', undefined);
        break;
      }
    }
  }

  // O placeholder de lazy-load do Taboola vem como background-image, onde o DOM
  // nao expoe tamanho nenhum — nao da pra reconhece-lo medindo. Mas da pra
  // reconhecer pela repeticao: um mesmo arquivo pintado em varios cards da
  // mesma pagina nao e criativo. Criativo e unico por anuncio; placeholder e
  // logo de parceiro se repetem. Na pagina que motivou isso eram 42 copias.
  // Conta pela URL inteira, com query: em rede como a adnxs o criativo inteiro
  // vive nos parametros (shftr.adnxs.net/r?url=...), e ignorar a query juntaria
  // anuncios diferentes no mesmo balde — descartando material legitimo.
  const usos = {};
  for (const item of out) {
    usos[item.image_url] = (usos[item.image_url] || 0) + 1;
  }
  return out.filter(item => usos[item.image_url] < 4);
}
"""


# ---------------------------------------------------------------------------
# Coletor de links de materia. O widget de ad nativo vive no fim do artigo,
# nao na home — sem entrar nas materias o retorno de varios publishers e zero.
# ---------------------------------------------------------------------------

ARTICLE_LINKS_JS = r"""
(limit) => {
  const host = location.host;
  const seen = new Set();
  const out = [];
  // /sc/ e /show/ sao hub de seccao, nao materia — e hub nao carrega widget.
  const BLOCK = /\/(video|videos|live|tag|tags|topic|topics|category|categories|section|author|authors|subscribe|account|login|newsletter|shop|podcast|search|sc|show|hub|series)\//i;

  // mesmo motivo do extrator: o feed do MSN vive dentro de shadow root
  const allAnchors = () => {
    const found = [...document.querySelectorAll('a[href]')];
    const walk = (root) => {
      let nodes;
      try { nodes = root.querySelectorAll('*'); } catch (e) { return; }
      for (const el of nodes) {
        if (!el.shadowRoot) continue;
        found.push(...el.shadowRoot.querySelectorAll('a[href]'));
        walk(el.shadowRoot);
      }
    };
    walk(document);
    return found;
  };

  for (const a of allAnchors()) {
    let u;
    try { u = new URL(a.getAttribute('href'), location.href); } catch (e) { continue; }
    if (u.host !== host || !/^https?:$/.test(u.protocol)) continue;

    const path = u.pathname;
    if (BLOCK.test(path)) continue;
    // Sem exigir profundidade: o Business Insider publica em /slug-2026-9, um
    // nivel so. Quem separa materia de pagina de seccao e o slug abaixo.
    // slug de materia ("algo-assim-aqui") ou caminho com data (/2026/09/)
    if (!/[a-z]{3,}-[a-z]{3,}-[a-z]{3,}/i.test(path) && !/\/\d{4}\/\d{1,2}\//.test(path)) continue;

    const clean = u.origin + path;
    if (clean === location.origin + location.pathname || seen.has(clean)) continue;
    seen.add(clean);

    out.push(clean);
    if (out.length >= 250) break;
  }

  // Amostra espalhada em vez dos primeiros: o topo da pagina e menu e chamada
  // de seccao, e o meio/fim e onde estao as materias de verdade.
  if (out.length <= limit) return out;
  const step = out.length / limit;
  const picked = [];
  for (let i = 0; i < limit; i++) picked.push(out[Math.floor(i * step + step / 2)]);
  return picked;
}
"""
