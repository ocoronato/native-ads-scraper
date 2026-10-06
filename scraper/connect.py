"""Descoberta de navegador ja aberto (MoreLogin, AdsPower, Dolphin, Chrome).

Antidetect browser sobe um Chrome comum com porta de debug aberta. Achando
essa porta, o Playwright pluga nele por CDP e passa a dirigir o perfil do
MoreLogin — com o proxy, o fingerprint e os cookies que o perfil ja tem.
E assim que se coleta o pool americano de um IP brasileiro.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Portas que um navegador em modo debug costuma escutar em 127.0.0.1.
_LISTEN_RE = re.compile(
    r"^\s*TCP\s+(?:127\.0\.0\.1|0\.0\.0\.0|\[::1\]):(\d+)\s+\S+\s+LISTENING",
    re.IGNORECASE | re.MULTILINE,
)


def _listening_ports() -> list[int]:
    """Portas TCP em LISTENING na maquina (via netstat, sem dependencia extra)."""
    try:
        # Sem text=True de proposito: o netstat do Windows escreve na codepage
        # do sistema, nao em UTF-8, e um unico byte acentuado derrubava a
        # descoberta inteira. Lemos bytes e decodificamos tolerando lixo — so
        # interessam os digitos da porta.
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out = (completed.stdout or b"").decode("utf-8", "replace")
    ports = {int(m.group(1)) for m in _LISTEN_RE.finditer(out)}
    # Porta de debug e sempre alta e aleatoria; abaixo disso e servico comum.
    return sorted(p for p in ports if p > 1024)


def _probe(port: int, timeout: float = 0.4) -> tuple[int, str] | None:
    """Um endpoint CDP responde /json/version dizendo qual navegador e."""
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        # Sondagem, nao chamada: estamos batendo em portas locais quaisquer, e
        # do outro lado pode haver qualquer coisa — um servico que devolve lixo
        # binario levanta http.client.BadStatusLine, que nao e OSError e
        # derrubava a descoberta inteira. Aqui, qualquer erro so quer dizer
        # "nao e um navegador".
        return None
    browser = data.get("Browser")
    return (port, browser) if browser else None


def discover_cdp_endpoints(max_workers: int = 64) -> list[tuple[int, str]]:
    """Varre as portas locais e devolve as que sao endpoint de DevTools."""
    ports = _listening_ports()
    if not ports:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = pool.map(_probe, ports)
    return sorted(r for r in results if r)


def resolve_cdp(value: str) -> str:
    """Traduz o que veio no --cdp para uma URL http utilizavel.

    Aceita 'auto' (procura sozinho), um numero de porta, ou a URL completa.
    """
    value = (value or "").strip()

    if value.lower() == "auto":
        found = discover_cdp_endpoints()
        if not found:
            raise RuntimeError(
                "Nenhum navegador com porta de debug aberta.\n"
                "Abra o perfil no MoreLogin primeiro e rode de novo."
            )
        if len(found) > 1:
            listing = "\n".join(f"   porta {p}  ->  {b}" for p, b in found)
            print(f"[info] mais de um navegador aberto:\n{listing}")
        # Edge costuma ser o navegador do sistema ou do proprio app; perfil de
        # antidetect e Chromium e se apresenta como Chrome. Na duvida, Chrome.
        chrome = [item for item in found if item[1].startswith("Chrome/")]
        port, browser = (chrome or found)[0]
        print(f"[info] conectando em 127.0.0.1:{port} ({browser})")
        return f"http://127.0.0.1:{port}"

    if value.isdigit():
        return f"http://127.0.0.1:{value}"
    if not value.startswith("http"):
        return f"http://{value}"
    return value


# ---------------------------------------------------------------------------
# API local do MoreLogin. Nesta instalacao ela responde sem autenticacao, entao
# da pra iniciar um perfil pelo id/nome sem precisar de API Key.
# ---------------------------------------------------------------------------

MORELOGIN_API = "http://127.0.0.1:40000"


class MoreLoginError(RuntimeError):
    pass


class MoreLogin:
    def __init__(self, base: str = MORELOGIN_API, timeout: float = 30.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError) as exc:
            raise MoreLoginError(
                f"MoreLogin nao respondeu em {self.base} — o app esta aberto? ({exc})"
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise MoreLoginError(f"resposta ilegivel do MoreLogin: {exc}") from exc

        if str(body.get("code")) not in ("0", "None", "null"):
            raise MoreLoginError(f"{body.get('msg') or 'erro'} (code {body.get('code')})")
        return body.get("data") or {}

    def profiles(self, max_pages: int = 40, size: int = 50) -> list[dict]:
        """Lista todos os perfis, paginando ate acabar."""
        found: list[dict] = []
        for page_no in range(1, max_pages + 1):
            data = self._post("/api/env/page", {"pageNo": page_no, "pageSize": size})
            batch = data.get("dataList") or []
            if not batch:
                break
            found.extend(batch)
        return found

    def resolve(self, query: str) -> dict:
        """Acha um perfil por id exato ou por nome (exato, depois parcial)."""
        query = query.strip()
        everything = self.profiles()

        for profile in everything:
            if str(profile.get("id")) == query:
                return profile
        exact = [p for p in everything if str(p.get("envName", "")).strip() == query]
        if len(exact) == 1:
            return exact[0]

        partial = [
            p for p in everything if query.lower() in str(p.get("envName", "")).lower()
        ]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            names = ", ".join(sorted(str(p.get("envName")) for p in partial)[:8])
            raise MoreLoginError(f"'{query}' casa com mais de um perfil: {names}")
        raise MoreLoginError(
            f"nenhum perfil chamado '{query}' entre os {len(everything)} da conta"
        )

    def start(self, env_id: str) -> str:
        """Sobe o perfil e devolve a URL de CDP dele."""
        data = self._post("/api/env/start", {"envId": str(env_id)})
        # A chave da porta muda conforme a versao; aceitamos as variantes.
        for key in ("debugPort", "debug_port", "port", "debuggerPort"):
            port = data.get(key)
            if port:
                return f"http://127.0.0.1:{port}"
        address = data.get("webdriver") or data.get("wsEndpoint") or ""
        if isinstance(address, str) and address.startswith(("http", "ws")):
            return address
        raise MoreLoginError(
            f"perfil subiu mas nao achei a porta de debug na resposta: {data}"
        )

    def close(self, env_id: str) -> None:
        try:
            self._post("/api/env/close", {"envId": str(env_id)})
        except MoreLoginError:
            pass  # fechar e cortesia; nao vale derrubar a coleta por isso
