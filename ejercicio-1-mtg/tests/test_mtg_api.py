"""Cliente de la API de cartas: traduccion de filtros y lo que la API no sabe hacer."""

from __future__ import annotations

import httpx
import pytest

from mtg_assistant.clients.mtg_api import MTGApiClient, MTGApiError, normalize_color
from mtg_assistant.config import Settings
from mtg_assistant.models import CardSearchFilters


def _client(handler, settings: Settings | None = None) -> MTGApiClient:
    settings = settings or Settings(mtg_api_base_url="https://api.test/v1")
    return MTGApiClient(
        settings=settings,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url=settings.mtg_api_base_url
        ),
    )


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("blanco", "W"), ("White", "W"), ("w", "W"), ("rojo", "R"), ("azul", "U")],
)
def test_normalize_color(entrada: str, esperado: str) -> None:
    assert normalize_color(entrada) == esperado


def test_color_desconocido_devuelve_none() -> None:
    assert normalize_color("turquesa") is None


def test_colores_and_usa_coma_y_or_usa_pipe(mtg_client: MTGApiClient, api_calls) -> None:
    mtg_client.search_cards(CardSearchFilters(colors=["blanco", "rojo"], color_match="and"))
    assert api_calls[-1].url.params["colors"] == "W,R"

    mtg_client.search_cards(CardSearchFilters(colors=["blanco", "rojo"], color_match="or"))
    assert api_calls[-1].url.params["colors"] == "W|R"


def test_subtipos_y_tipos_viajan_como_and(mtg_client: MTGApiClient, api_calls) -> None:
    mtg_client.search_cards(
        CardSearchFilters(types=["Creature"], subtypes=["Human", "Warrior"])
    )
    params = api_calls[-1].url.params
    assert params["types"] == "Creature"
    assert params["subtypes"] == "Human,Warrior"


def test_el_rango_de_cmc_se_filtra_en_cliente(mtg_client: MTGApiClient, api_calls) -> None:
    """La API solo acepta `cmc` exacto: el rango no debe viajar en la query."""
    cards = mtg_client.search_cards(CardSearchFilters(cmc_max=1))
    assert "cmc" not in api_calls[-1].url.params
    assert cards
    assert all(card.cmc is not None and card.cmc <= 1 for card in cards)
    assert "Wojek Halberdiers" not in [c.name for c in cards]  # CMC 3


def test_cmc_min_excluye_las_baratas(mtg_client: MTGApiClient) -> None:
    cards = mtg_client.search_cards(CardSearchFilters(cmc_min=2))
    assert [c.name for c in cards] == ["Wojek Halberdiers"]


def test_el_limite_corta_los_resultados(mtg_client: MTGApiClient) -> None:
    assert len(mtg_client.search_cards(CardSearchFilters(cmc_max=10, limit=1))) == 1


def test_carta_sin_cmc_no_pasa_un_filtro_de_rango() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"cards": [{"name": "Rara sin CMC"}]})

    assert _client(handler).search_cards(CardSearchFilters(cmc_max=5)) == []


def test_get_card_prefiere_el_nombre_exacto() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"cards": [{"name": "Shock Troops"}, {"name": "Shock", "cmc": 1.0}]},
        )

    card = _client(handler).get_card_by_name("Shock")
    assert card is not None and card.name == "Shock"


def test_get_card_devuelve_none_si_no_hay_nada() -> None:
    handler = lambda _: httpx.Response(200, json={"cards": []})  # noqa: E731
    assert _client(handler).get_card_by_name("Carta Inexistente") is None


def test_los_sets_salen_ordenados_por_fecha_descendente(mtg_client: MTGApiClient) -> None:
    sets = mtg_client.list_recent_sets(limit=2)
    assert [s.code for s in sets] == ["OTJ", "MKM"]


def test_el_429_se_traduce_a_un_error_legible() -> None:
    handler = lambda _: httpx.Response(429, text="Rate Limit Exceeded")  # noqa: E731
    with pytest.raises(MTGApiError, match="Limite de peticiones"):
        _client(handler).search_cards(CardSearchFilters())


def test_el_500_se_traduce_a_MTGApiError() -> None:
    handler = lambda _: httpx.Response(500)  # noqa: E731
    with pytest.raises(MTGApiError, match="500"):
        _client(handler).search_cards(CardSearchFilters())


def test_un_fallo_de_red_no_escapa_como_httpx_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin DNS")

    with pytest.raises(MTGApiError, match="No se pudo contactar"):
        _client(handler).search_cards(CardSearchFilters())


def test_json_invalido_se_traduce() -> None:
    handler = lambda _: httpx.Response(200, text="<html>nope</html>")  # noqa: E731
    with pytest.raises(MTGApiError, match="no-JSON"):
        _client(handler).search_cards(CardSearchFilters())
