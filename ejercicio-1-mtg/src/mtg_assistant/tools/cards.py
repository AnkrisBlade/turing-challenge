"""Herramientas sobre la API publica de cartas (api.magicthegathering.io)."""

from __future__ import annotations

from typing import Any

from mtg_assistant.clients.mtg_api import MTGApiError, normalize_color
from mtg_assistant.models import Card, CardSearchFilters, Citation
from mtg_assistant.tools.base import Tool, ToolContext, ToolResult

MAX_LIMIT = 20


def _format_card(card: Card) -> str:
    bits = [card.name]
    if card.mana_cost:
        bits.append(card.mana_cost)
    if card.cmc is not None:
        bits.append(f"CMC {card.cmc:g}")
    line = " | ".join(bits)
    detail = card.type_line or ""
    if card.power is not None and card.toughness is not None:
        detail += f" {card.power}/{card.toughness}"
    text = (card.text or "").replace("\n", " ")
    out = f"- {line}\n  {detail.strip()}"
    if text:
        out += f"\n  {text}"
    if card.set_name:
        out += f"\n  Edicion: {card.set_name}"
    return out


def _cards_payload(cards: list[Card]) -> dict[str, Any]:
    return {"cards": [card.model_dump() for card in cards]}


def search_cards(context: ToolContext, **kwargs: Any) -> ToolResult:
    raw_colors = kwargs.get("colors") or []
    unknown = [c for c in raw_colors if normalize_color(c) is None]
    if unknown:
        return ToolResult.error(
            f"Colores no reconocidos: {', '.join(unknown)}. "
            "Usa W, U, B, R, G o sus nombres en espanol."
        )

    filters = CardSearchFilters(
        name=kwargs.get("name"),
        colors=raw_colors,
        color_match=kwargs.get("color_match", "and"),
        types=kwargs.get("types") or [],
        subtypes=kwargs.get("subtypes") or [],
        text=kwargs.get("text"),
        rarity=kwargs.get("rarity"),
        set_code=kwargs.get("set_code"),
        cmc=kwargs.get("cmc"),
        cmc_min=kwargs.get("cmc_min"),
        cmc_max=kwargs.get("cmc_max"),
        limit=max(1, min(int(kwargs.get("limit", 10)), MAX_LIMIT)),
    )

    try:
        cards = context.mtg_client.search_cards(filters)
    except MTGApiError as exc:
        return ToolResult.error(str(exc))

    if not cards:
        return ToolResult(
            content=(
                "Ninguna carta cumple esos filtros. Sugiere al cliente relajar alguno "
                "(color, coste o subtipo) en vez de inventar cartas."
            ),
            summary="0 cartas",
        )

    body = "\n".join(_format_card(card) for card in cards)
    return ToolResult(
        content=f"{len(cards)} cartas encontradas:\n{body}",
        summary=f"{len(cards)} cartas",
        citations=[
            Citation(kind="card", label=card.name, detail=card.set_name) for card in cards
        ],
        payload=_cards_payload(cards),
    )


def get_card(context: ToolContext, name: str) -> ToolResult:
    name = (name or "").strip()
    if not name:
        return ToolResult.error("Falta el nombre de la carta.")
    try:
        card = context.mtg_client.get_card_by_name(name)
    except MTGApiError as exc:
        return ToolResult.error(str(exc))

    if card is None:
        return ToolResult(
            content=(
                f"No existe ninguna carta llamada '{name}'. Puede ser una traduccion "
                "libre del cliente: pidele el nombre en ingles o describe la carta."
            ),
            summary=f"'{name}' no encontrada",
        )

    return ToolResult(
        content=f"Ficha oficial:\n{_format_card(card)}",
        summary=f"ficha de {card.name}",
        citations=[Citation(kind="card", label=card.name, detail=card.set_name)],
        payload=_cards_payload([card]),
    )


def list_recent_sets(context: ToolContext, limit: int = 10) -> ToolResult:
    limit = max(1, min(int(limit), MAX_LIMIT))
    try:
        sets = context.mtg_client.list_recent_sets(limit=limit)
    except MTGApiError as exc:
        return ToolResult.error(str(exc))

    if not sets:
        return ToolResult(content="La API no devolvio ediciones.", summary="0 ediciones")

    body = "\n".join(
        f"- {s.name} ({s.code}) - {s.release_date or 'sin fecha'} [{s.set_type or '?'}]"
        for s in sets
    )
    return ToolResult(
        content=f"Ediciones mas recientes:\n{body}",
        summary=f"{len(sets)} ediciones",
        citations=[Citation(kind="set", label=s.name, detail=s.release_date) for s in sets],
    )


SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Parte del nombre de la carta."},
        "colors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Colores en W/U/B/R/G o nombre ('blanco', 'rojo').",
        },
        "color_match": {
            "type": "string",
            "enum": ["and", "or"],
            "description": "'and' = la carta tiene todos esos colores; 'or' = alguno.",
        },
        "types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Tipos en ingles: Creature, Instant, Sorcery, Artifact...",
        },
        "subtypes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Subtipos en ingles: Warrior, Goblin, Equipment...",
        },
        "text": {
            "type": "string",
            "description": "Texto que debe aparecer en las reglas de la carta, en ingles.",
        },
        "rarity": {"type": "string", "description": "Common, Uncommon, Rare, Mythic Rare."},
        "set_code": {"type": "string", "description": "Codigo de edicion, p.ej. 'KTK'."},
        "cmc": {"type": "number", "description": "Coste convertido exacto."},
        "cmc_min": {"type": "number", "description": "Coste convertido minimo (inclusive)."},
        "cmc_max": {"type": "number", "description": "Coste convertido maximo (inclusive)."},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
    },
    "additionalProperties": False,
}

SEARCH_TOOL = Tool(
    name="search_cards",
    description=(
        "Busca cartas reales por atributos. Traduce la descripcion del cliente a "
        "filtros: 'carta blanca de coste inferior a dos que sea guerrero' -> "
        "colors=['W'], cmc_max=1, types=['Creature'], subtypes=['Warrior']. "
        "Ojo: 'inferior a dos' es cmc_max=1, no cmc_max=2. Los tipos y subtipos "
        "van SIEMPRE en ingles aunque el cliente escriba en espanol."
    ),
    input_schema=SEARCH_SCHEMA,
    handler=search_cards,
)

GET_CARD_TOOL = Tool(
    name="get_card",
    description=(
        "Recupera la ficha oficial de una carta concreta por nombre (texto de reglas, "
        "coste, fuerza/resistencia). Usala cuando el cliente mencione cartas por su "
        "nombre en una pregunta de interaccion, antes de razonar sobre ellas."
    ),
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Nombre de la carta."}},
        "required": ["name"],
        "additionalProperties": False,
    },
    handler=get_card,
)

LIST_SETS_TOOL = Tool(
    name="list_recent_sets",
    description="Lista las ediciones/releases mas recientes ordenadas por fecha de salida.",
    input_schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT}},
        "additionalProperties": False,
    },
    handler=list_recent_sets,
)
