"""Abre o publisher num Chromium real, rola a pagina e colhe o que aparece.

Widget de ad nativo quase sempre fica abaixo da dobra e so carrega quando
entra na viewport. Por isso a rolagem incremental com pausa: sem ela a
pagina devolve zero criativo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Response, TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from .adapters import (
    AD_CLICK_HOSTS,
    ARTICLE_LINKS_JS,
    DOM_EXTRACTOR_JS,
    is_ad_api,
    network_of,
    parse_ad_payload,
)

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
)


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    user_agent: str
    viewport: dict
    is_mobile: bool
    scale: int


DEVICES = {
    "desktop": DeviceProfile("desktop", UA_DESKTOP, {"width": 1440, "height": 900}, False, 1),
    "mobile": DeviceProfile("mobile", UA_MOBILE, {"width": 390, "height": 844}, True, 3),
}

# Preferimos sempre RECUSAR o consentimento: a coleta nao precisa de cookie de
# publicidade, e aceitar em nome de alguem nao e papel de um raspador.
CONSENT_REJECT = (
    "#onetrust-reject-all-handler",
    "button[name='reject']",
    "button[title='Reject All']",
    "button[aria-label*='Reject' i]",
    "#truste-consent-required",
    ".fc-cta-do-not-consent",
    "button:has-text('Reject all')",
    "button:has-text('Reject All')",
    "button:has-text('Decline')",
    "button:has-text('Recusar')",
    "button:has-text('Continuar sem aceitar')",
    "button:has-text('Continue without accepting')",
)
# So fecha o banner, sem aceitar nada.
CONSENT_DISMISS = (
    "button[aria-label*='Close' i]",
    "button[aria-label*='Fechar' i]",
    ".modal-close",
)


def dismiss_consent(page: Page) -> str:
    """Tenta recusar o banner de cookies; se nao houver 'recusar', so fecha."""
    for group, label in ((CONSENT_REJECT, "rejeitado"), (CONSENT_DISMISS, "fechado")):
        for selector in group:
            try:
                node = page.locator(selector).first
                if node.is_visible(timeout=600):
                    node.click(timeout=2500, no_wait_after=True)
                    page.wait_for_timeout(900)
                    return label
            except (PlaywrightError, PlaywrightTimeout):
                continue
    return "ausente"


def _scroll_and_settle(page: Page, steps: int, pause_ms: int) -> None:
    try:
        step_px = int(page.evaluate("Math.round(window.innerHeight * 0.85)") or 900)
    except PlaywrightError:
        step_px = 900
    for step in range(steps):
        page.mouse.wheel(0, step_px)
        page.wait_for_timeout(pause_ms)
        if step % 3 == 2:
            # Dar uma respirada no topo faz alguns widgets lazy dispararem.
            try:
                page.evaluate("window.scrollBy(0, -300)")
            except PlaywrightError:
                pass
            page.wait_for_timeout(400)


def _extract_dom(page: Page, sponsored_only: bool) -> list[dict]:
    """Roda o extrator no documento principal e em cada iframe."""
    found: list[dict] = []
    for frame in page.frames:
        try:
            items = frame.evaluate(DOM_EXTRACTOR_JS, list(AD_CLICK_HOSTS))
        except (PlaywrightError, PlaywrightTimeout):
            continue
        for item in items or []:
            # Sem isso entra a recomendacao editorial do proprio portal.
            if sponsored_only and not item.get("paid"):
                continue
            found.append(item)
    return found


def _drain_responses(responses: list[Response], sponsored_only: bool) -> list[dict]:
    """Le o corpo das respostas de API de widget que interceptamos."""
    found: list[dict] = []
    for response in responses:
        try:
            body = response.text()
        except (PlaywrightError, PlaywrightTimeout):
            continue
        network = network_of(response.url)
        for item in parse_ad_payload(body, sponsored_only=sponsored_only):
            item["network"] = network
            found.append(item)
    return found


def harvest_url(
    context,
    url: str,
    *,
    scrolls: int,
    pause_ms: int,
    sponsored_only: bool,
    collect_links: int = 0,
    timeout_ms: int = 45_000,
) -> tuple[list[dict], str, list[str]]:
    """Visita uma URL e devolve (itens brutos, status legivel, links de materia)."""
    page = context.new_page()
    captured: list[Response] = []

    def on_response(response: Response) -> None:
        # trc.taboola.com tambem dispara dezenas de pixels de tracking; so
        # interessa a resposta que e JSON de verdade.
        if not is_ad_api(response.url):
            return
        try:
            content_type = response.headers.get("content-type", "")
        except PlaywrightError:
            return
        if "json" in content_type.lower():
            captured.append(response)

    page.on("response", on_response)

    items: list[dict] = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except (PlaywrightError, PlaywrightTimeout) as exc:
        page.close()
        return [], f"falhou ao abrir ({type(exc).__name__})", []

    links: list[str] = []
    incidente = ""

    # Aba que fecha no meio nao pode derrubar a coleta inteira. Num perfil de
    # antidetect isso acontece — a pessoa mexe no navegador, o MoreLogin
    # reinicia o perfil, a conexao CDP cai. Aqui a gente guarda o que ja
    # conseguiu, registra o motivo e devolve pro chamador seguir pra proxima
    # URL, em vez de perder 20 minutos de rodada por uma pagina.
    try:
        consent = dismiss_consent(page)
        page.wait_for_timeout(1500)

        # Extrai a cada rodada de rolagem: carrossel troca de item conforme rola.
        rounds = max(1, scrolls // 3)
        per_round = max(1, scrolls // rounds)
        for _ in range(rounds):
            _scroll_and_settle(page, per_round, pause_ms)
            items.extend(_extract_dom(page, sponsored_only))

        # Uma ultima passada depois de esperar de verdade: o widget pinta um
        # placeholder e troca pela imagem real quando ela chega. Extrair cedo
        # demais grava o placeholder e perde o criativo.
        page.wait_for_timeout(3000)
        items.extend(_extract_dom(page, sponsored_only))

        # Os links so sao colhidos depois de rolar: home de portal carrega o
        # feed por scroll, e antes disso quase nao ha link de materia.
        if collect_links:
            try:
                links = page.evaluate(ARTICLE_LINKS_JS, collect_links) or []
            except (PlaywrightError, PlaywrightTimeout):
                links = []
    except (PlaywrightError, PlaywrightTimeout) as exc:
        consent = "interrompido"
        incidente = f", INTERROMPIDO ({type(exc).__name__})"

    items.extend(_drain_responses(captured, sponsored_only))
    try:
        page.close()
    except (PlaywrightError, PlaywrightTimeout):
        pass
    return items, f"consent={consent}, apis={len(captured)}{incidente}", links


def limpar_abas_nossas(context, hosts: set[str], verbose: bool = True) -> int:
    """Fecha abas de coleta que sobraram de execucoes anteriores.

    Quando o processo e morto no meio (limite de tempo, Ctrl+C, queda), o
    page.close() nunca roda e a aba fica no perfil. Num navegador que a pessoa
    deixa aberto o dia todo isso acumula: cada pagina de portal continua viva
    carregando iframe de sincronizacao de cookie, e o perfil trava.

    So fecha o que e reconhecidamente nosso — aba cujo host esta na lista de
    publishers. Aba que a pessoa abriu fica onde esta.
    """
    fechadas = 0
    for pagina in list(context.pages):
        try:
            url = pagina.url or ""
        except PlaywrightError:
            continue
        if not url.startswith("http"):
            continue
        try:
            host = urlparse(url).netloc.lower().removeprefix("www.")
        except ValueError:
            continue
        if any(host == h or host.endswith("." + h) for h in hosts):
            try:
                pagina.close()
                fechadas += 1
            except PlaywrightError:
                pass
    if fechadas and verbose:
        print(f"[info] fechei {fechadas} aba(s) de coleta que ficaram de execucoes anteriores")
    return fechadas


class BrowserSession:
    """Context manager fino em cima do Playwright.

    Dois modos. No normal sobe um Chromium proprio e finge o device. No modo
    CDP pluga num navegador ja aberto — tipicamente um perfil do MoreLogin com
    proxy americano — e ali nao mexemos em user-agent, viewport nem locale: o
    perfil antidetect ja tem um fingerprint coerente, e sobrescrever justamente
    os campos que ele cuidou e a maneira mais rapida de ser detectado.
    """

    def __init__(
        self,
        device: str,
        headless: bool = True,
        locale: str = "en-US",
        timezone: str | None = None,
        proxy: dict | None = None,
        cdp_url: str | None = None,
    ):
        self.profile = DEVICES[device]
        self.headless = headless
        self.locale = locale
        self.timezone = timezone
        self.proxy = proxy
        self.cdp_url = cdp_url
        self._pw = None
        self._browser = None
        self.context = None

    @property
    def attached(self) -> bool:
        """True quando estamos usando o navegador de outra pessoa."""
        return bool(self.cdp_url)

    def __enter__(self):
        self._pw = sync_playwright().start()

        if self.cdp_url:
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
            contexts = self._browser.contexts
            # O perfil ja vem com um contexto (com os cookies e o proxy dele).
            self.context = contexts[0] if contexts else self._browser.new_context()
            self.context.set_default_timeout(20_000)
            return self

        launch: dict = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled", "--mute-audio"],
        }
        if self.proxy:
            launch["proxy"] = self.proxy
        self._browser = self._pw.chromium.launch(**launch)

        options: dict = {
            "user_agent": self.profile.user_agent,
            "viewport": self.profile.viewport,
            "is_mobile": self.profile.is_mobile,
            "has_touch": self.profile.is_mobile,
            "device_scale_factor": self.profile.scale,
            "locale": self.locale,
            "ignore_https_errors": True,
        }
        if self.timezone:
            options["timezone_id"] = self.timezone
        self.context = self._browser.new_context(**options)
        self.context.set_default_timeout(20_000)
        # Vídeo e fonte nao interessam e custam muito tempo de carga.
        self.context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("media", "font")
            else route.continue_(),
        )
        return self

    def __exit__(self, *exc) -> None:
        # Navegador que nao e nosso a gente so desconecta: fechar o contexto
        # mataria as abas do perfil do MoreLogin que a pessoa deixou abertas.
        closers = (self._browser,) if self.attached else (self.context, self._browser)
        for closer in closers:
            try:
                if closer:
                    closer.close()
            except PlaywrightError:
                pass
        if self._pw:
            self._pw.stop()


def polite_pause(seconds: float) -> None:
    """Respiro entre publishers — nao martelar o site."""
    time.sleep(seconds)
