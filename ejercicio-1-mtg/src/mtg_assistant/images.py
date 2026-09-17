"""Filtro de URLs de imagen que la UI puede pedir sin abrir un SSRF.

`st.image(url)` la descarga el proceso de Streamlit: el `image_url` de una
carta es una URL que elige un tercero y que pedimos nosotros. Si la API de
cartas devolviera `file:///etc/passwd` o `http://169.254.169.254/...`, quien
haria esa peticion seria la UI. Por eso solo pasan http(s) a hosts de arte
conocidos.

Lo que este filtro NO cubre: `MTG_API_BASE_URL` es configuracion del operador
y la UI anade su host a la lista via `extra_hosts`. Apuntar esa variable a un
host hostil sigue siendo una decision de quien despliega; aqui se confia en
ella a proposito, igual que se confia en el resto del entorno.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

# Gatherer es lo que sirve api.magicthegathering.io; Scryfall por si el
# cliente de cartas cambia de origen. Cualquier otro host no se pide.
DEFAULT_IMAGE_HOSTS = frozenset(
    {
        "gatherer.wizards.com",
        "cards.scryfall.io",
        "api.scryfall.com",
    }
)


def safe_card_image_url(
    url: str | None,
    extra_hosts: Iterable[str] = (),
) -> str | None:
    """Devuelve la URL si es http(s) a un host conocido; si no, None."""
    if not url or not str(url).strip():
        return None
    candidate = str(url).strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None
    allowed = DEFAULT_IMAGE_HOSTS | {
        h.lower().rstrip(".") for h in extra_hosts if h
    }
    # El sufijo admite subdominios ("www.gatherer.wizards.com"), y se aplica
    # tambien a `extra_hosts`: configurar 'api.test' acepta '*.api.test'. Vale
    # para un host que pone el operador, no para uno que venga de fuera.
    if host in allowed or any(host.endswith("." + known) for known in allowed):
        return candidate
    return None
