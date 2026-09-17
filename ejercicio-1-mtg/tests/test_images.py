"""La UI solo pide arte a hosts conocidos: un image_url hostil no se descarga."""

from __future__ import annotations

import pytest

from mtg_assistant.images import safe_card_image_url

GATHERER = (
    "http://gatherer.wizards.com/Handlers/Image.ashx?multiverseid=191089&type=card"
)
SCRYFALL = "https://cards.scryfall.io/normal/front/0/0/bolt.jpg"


@pytest.mark.parametrize("url", [GATHERER, SCRYFALL, "https://api.scryfall.com/cards/x/image"])
def test_los_origenes_de_arte_conocidos_pasan(url: str) -> None:
    assert safe_card_image_url(url) == url


def test_un_subdominio_del_host_conocido_tambien_pasa() -> None:
    url = "https://www.gatherer.wizards.com/Handlers/Image.ashx?multiverseid=1&type=card"
    assert safe_card_image_url(url) == url


def test_el_host_de_la_api_configurada_se_acepta_como_extra() -> None:
    url = "https://api.test/v1/lions.png"
    assert safe_card_image_url(url, extra_hosts=["api.test"]) == url


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "   ",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/admin",
        "https://evil.example/lions.png",
        "https://gatherer.wizards.com.evil.example/lions.png",
        "//gatherer.wizards.com/lions.png",
        "/static/lions.png",
    ],
)
def test_cualquier_otro_origen_se_descarta(url: str | None) -> None:
    assert safe_card_image_url(url) is None
