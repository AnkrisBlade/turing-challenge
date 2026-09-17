"""Contratos de datos compartidos entre agente, herramientas y API HTTP.

Regla del proyecto: un tipo se define una sola vez, aqui. Ni el router de
FastAPI ni las herramientas declaran formas de datos propias.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# RAG de reglas
# --------------------------------------------------------------------------
class RuleChunk(BaseModel):
    """Un fragmento citable del reglamento."""

    chunk_id: str = Field(description="Identificador estable, p.ej. 'rule-509.1a'")
    rule_number: str | None = Field(
        default=None, description="Numero de regla oficial si el texto lo trae"
    )
    section: str | None = Field(default=None, description="Titulo de seccion")
    page: int | None = Field(default=None, description="Pagina del PDF de origen")
    text: str


class RuleHit(BaseModel):
    """Un chunk recuperado junto con su score de relevancia."""

    chunk: RuleChunk
    score: float


# --------------------------------------------------------------------------
# Cartas
# --------------------------------------------------------------------------
class Card(BaseModel):
    """Proyeccion reducida de una carta de api.magicthegathering.io."""

    name: str
    mana_cost: str | None = None
    cmc: float | None = None
    colors: list[str] = Field(default_factory=list)
    type_line: str | None = None
    types: list[str] = Field(default_factory=list)
    subtypes: list[str] = Field(default_factory=list)
    rarity: str | None = None
    set_name: str | None = None
    text: str | None = None
    power: str | None = None
    toughness: str | None = None
    image_url: str | None = None


class CardSearchFilters(BaseModel):
    """Filtros normalizados que el modelo rellena al buscar cartas.

    `cmc_max` / `cmc_min` no existen en la API upstream (solo acepta `cmc`
    exacto), asi que se aplican en cliente tras paginar. Ver
    `clients/mtg_api.py`.
    """

    name: str | None = None
    colors: list[str] = Field(default_factory=list)
    color_match: Literal["and", "or"] = "and"
    types: list[str] = Field(default_factory=list)
    subtypes: list[str] = Field(default_factory=list)
    text: str | None = None
    rarity: str | None = None
    set_code: str | None = None
    cmc: float | None = None
    cmc_min: float | None = None
    cmc_max: float | None = None
    limit: int = 10


class CardSet(BaseModel):
    """Una edicion / release."""

    code: str
    name: str
    release_date: str | None = None
    set_type: str | None = None


# --------------------------------------------------------------------------
# Cartas custom (bonus)
# --------------------------------------------------------------------------
class CustomCard(BaseModel):
    """Carta inventada por el asistente, validada contra el marco de reglas."""

    name: str
    mana_cost: str = Field(description="Notacion oficial, p.ej. '{1}{R}{W}'")
    type_line: str
    rules_text: str
    flavor_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    colors: list[str] = Field(default_factory=list)
    rarity: str = "rare"
    design_notes: str | None = Field(
        default=None, description="Por que el coste/estadisticas son razonables"
    )


# --------------------------------------------------------------------------
# Conversacion
# --------------------------------------------------------------------------
class ToolCallTrace(BaseModel):
    """Traza de una herramienta ejecutada: es la 'base de referencia' visible."""

    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str


class Citation(BaseModel):
    """Referencia mostrable al usuario final."""

    kind: Literal["rule", "card", "set"]
    label: str
    detail: str | None = None


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    trace: list[ToolCallTrace] = Field(default_factory=list)
    # Cartas tocadas en el turno: la UI las usa para pintar las imagenes, que
    # el texto de la respuesta no puede dar.
    cards: list[Card] = Field(default_factory=list)
    custom_card: CustomCard | None = None
