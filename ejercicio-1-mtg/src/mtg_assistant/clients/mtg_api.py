"""Cliente de api.magicthegathering.io.

Dos cosas que la API upstream NO hace y resolvemos aqui:

1. `cmc` solo acepta un valor exacto -- no hay rangos. Las consultas del tipo
   "coste inferior a 2" se resuelven paginando candidatos y filtrando en
   cliente (`_matches_cmc_range`).
2. No hay orden por relevancia util para lenguaje natural, asi que
   truncamos con `limit` despues de filtrar.

El transporte se inyecta para que los tests sean hermeticos (sin red).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from mtg_assistant.config import Settings, get_settings
from mtg_assistant.models import Card, CardSearchFilters, CardSet

logger = logging.getLogger(__name__)

# Nombre completo -> inicial que espera la API en `colors`.
COLOR_ALIASES: dict[str, str] = {
    "w": "W", "white": "W", "blanco": "W", "blanca": "W",
    "u": "U", "blue": "U", "azul": "U",
    "b": "B", "black": "B", "negro": "B", "negra": "B",
    "r": "R", "red": "R", "rojo": "R", "roja": "R",
    "g": "G", "green": "G", "verde": "G",
}


def normalize_color(value: str) -> str | None:
    """'blanco' / 'White' / 'w' -> 'W'. Devuelve None si no se reconoce."""
    return COLOR_ALIASES.get(value.strip().lower())


class MTGApiError(RuntimeError):
    """La API upstream fallo o devolvio algo que no sabemos interpretar."""


class MTGApiClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(
            base_url=self.settings.mtg_api_base_url,
            timeout=self.settings.mtg_api_timeout,
            headers={"User-Agent": "turing-challenge-mtg-assistant/0.1"},
        )

    # -- HTTP ------------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:  # timeout, DNS, conexion...
            raise MTGApiError(f"No se pudo contactar con la API de cartas: {exc}") from exc

        if response.status_code == 429:
            raise MTGApiError("Limite de peticiones de la API de cartas alcanzado (5000/h).")
        if response.status_code >= 400:
            raise MTGApiError(
                f"La API de cartas respondio {response.status_code} para {path}."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MTGApiError("La API de cartas devolvio una respuesta no-JSON.") from exc

    # -- Cartas ----------------------------------------------------------
    def search_cards(self, filters: CardSearchFilters) -> list[Card]:
        """Busca cartas y aplica los filtros que la API no soporta."""
        params = self._build_params(filters)
        needs_client_side = filters.cmc_min is not None or filters.cmc_max is not None

        collected: list[Card] = []
        max_pages = self.settings.mtg_api_max_pages if needs_client_side else 1
        for page in range(1, max_pages + 1):
            payload = self._get("/cards", {**params, "page": page})
            raw_cards = payload.get("cards", [])
            if not raw_cards:
                break
            for raw in raw_cards:
                card = _card_from_api(raw)
                if not _matches_cmc_range(card, filters):
                    continue
                collected.append(card)
                if len(collected) >= filters.limit:
                    return collected
            if len(raw_cards) < params["pageSize"]:
                break  # ultima pagina
        return collected

    def get_card_by_name(self, name: str) -> Card | None:
        """Busca por nombre exacto; si no hay match exacto, el primer parcial."""
        payload = self._get("/cards", {"name": name, "pageSize": 20})
        raw_cards = payload.get("cards", [])
        if not raw_cards:
            return None
        wanted = name.strip().lower()
        for raw in raw_cards:
            if str(raw.get("name", "")).strip().lower() == wanted:
                return _card_from_api(raw)
        return _card_from_api(raw_cards[0])

    # -- Ediciones -------------------------------------------------------
    def list_recent_sets(self, limit: int = 10) -> list[CardSet]:
        payload = self._get("/sets", {})
        sets = [
            CardSet(
                code=raw.get("code", ""),
                name=raw.get("name", ""),
                release_date=raw.get("releaseDate"),
                set_type=raw.get("type"),
            )
            for raw in payload.get("sets", [])
        ]
        # `releaseDate` es ISO (YYYY-MM-DD), asi que ordena bien como string.
        sets.sort(key=lambda s: s.release_date or "", reverse=True)
        return sets[:limit]

    # -- Internos --------------------------------------------------------
    def _build_params(self, filters: CardSearchFilters) -> dict[str, Any]:
        """Traduce filtros normalizados a query params de la API.

        Delimitadores upstream: coma = AND, pipe = OR.
        """
        params: dict[str, Any] = {"pageSize": self.settings.mtg_api_page_size}

        if filters.name:
            params["name"] = filters.name
        if filters.colors:
            codes = [c for c in (normalize_color(c) for c in filters.colors) if c]
            if codes:
                sep = "," if filters.color_match == "and" else "|"
                params["colors"] = sep.join(codes)
        if filters.types:
            params["types"] = ",".join(filters.types)
        if filters.subtypes:
            params["subtypes"] = ",".join(filters.subtypes)
        if filters.text:
            params["text"] = filters.text
        if filters.rarity:
            params["rarity"] = filters.rarity
        if filters.set_code:
            params["set"] = filters.set_code
        if filters.cmc is not None:
            params["cmc"] = filters.cmc
        return params


def _matches_cmc_range(card: Card, filters: CardSearchFilters) -> bool:
    if filters.cmc_min is None and filters.cmc_max is None:
        return True
    if card.cmc is None:
        return False
    if filters.cmc_min is not None and card.cmc < filters.cmc_min:
        return False
    if filters.cmc_max is not None and card.cmc > filters.cmc_max:
        return False
    return True


def _card_from_api(raw: dict[str, Any]) -> Card:
    return Card(
        name=raw.get("name", ""),
        mana_cost=raw.get("manaCost"),
        cmc=raw.get("cmc"),
        colors=raw.get("colors") or [],
        type_line=raw.get("type"),
        types=raw.get("types") or [],
        subtypes=raw.get("subtypes") or [],
        rarity=raw.get("rarity"),
        set_name=raw.get("setName"),
        text=raw.get("text"),
        power=raw.get("power"),
        toughness=raw.get("toughness"),
        image_url=raw.get("imageUrl"),
    )
