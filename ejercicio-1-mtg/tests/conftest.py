"""Fixtures compartidas.

Toda la suite es hermetica: sin red, sin claves y sin ficheros del cliente.
El LLM y la API de cartas se sustituyen por dobles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from mtg_assistant.agent import MTGAgent
from mtg_assistant.clients.mtg_api import MTGApiClient
from mtg_assistant.config import Settings
from mtg_assistant.rag.chunker import chunk_document
from mtg_assistant.rag.index import RulesIndex
from mtg_assistant.tools import ToolContext

FIXTURES = Path(__file__).parent / "fixtures"

SAMPLE_CARDS: list[dict[str, Any]] = [
    {
        "name": "Savannah Lions", "manaCost": "{W}", "cmc": 1.0, "colors": ["White"],
        "type": "Creature - Cat", "types": ["Creature"], "subtypes": ["Cat"],
        "rarity": "Rare", "setName": "Limited Edition Alpha", "power": "2",
        "toughness": "1", "imageUrl": "https://example.test/lions.png",
    },
    {
        "name": "Mardu Woe-Reaper", "manaCost": "{W}", "cmc": 1.0, "colors": ["White"],
        "type": "Creature - Human Warrior", "types": ["Creature"],
        "subtypes": ["Human", "Warrior"], "rarity": "Common",
        "setName": "Fate Reforged", "power": "2", "toughness": "1",
        "text": "When Mardu Woe-Reaper enters the battlefield, exile target card.",
    },
    {
        "name": "Wojek Halberdiers", "manaCost": "{1}{R}{W}", "cmc": 3.0,
        "colors": ["Red", "White"], "type": "Creature - Human Soldier",
        "types": ["Creature"], "subtypes": ["Human", "Soldier"], "rarity": "Common",
        "setName": "Dragon's Maze", "text": "First strike", "power": "3",
        "toughness": "2",
    },
    {
        "name": "Lightning Bolt", "manaCost": "{R}", "cmc": 1.0, "colors": ["Red"],
        "type": "Instant", "types": ["Instant"], "subtypes": [],
        "rarity": "Common", "setName": "Limited Edition Alpha",
        "text": "Lightning Bolt deals 3 damage to any target.",
    },
    {
        "name": "Lightning Bolt", "manaCost": "{R}", "cmc": 1.0, "colors": ["Red"],
        "type": "Instant", "types": ["Instant"], "subtypes": [],
        "rarity": "Common", "setName": "Magic 2010",
        "text": "Lightning Bolt deals 3 damage to any target.",
        "imageUrl": "https://gatherer.wizards.com/Handlers/Image.ashx?multiverseid=191089&type=card",
    },
]

SAMPLE_SETS: list[dict[str, Any]] = [
    {
        "code": "OTJ", "name": "Outlaws of Thunder Junction",
        "releaseDate": "2024-04-19", "type": "expansion",
    },
    {
        "code": "MKM", "name": "Murders at Karlov Manor",
        "releaseDate": "2024-02-09", "type": "expansion",
    },
    {
        "code": "LEA", "name": "Limited Edition Alpha",
        "releaseDate": "1993-08-05", "type": "core",
    },
]


@pytest.fixture
def rules_text() -> str:
    return (FIXTURES / "reglamento_mini.txt").read_text(encoding="utf-8")


@pytest.fixture
def rules_index(rules_text: str) -> RulesIndex:
    return RulesIndex(chunk_document(rules_text))


@pytest.fixture
def settings() -> Settings:
    return Settings(mtg_api_base_url="https://api.test/v1", mtg_api_page_size=2)


@pytest.fixture
def api_calls() -> list[httpx.Request]:
    """Acumula las peticiones que el cliente lanza, para poder aseverarlas."""
    return []


@pytest.fixture
def mtg_client(settings: Settings, api_calls: list[httpx.Request]) -> MTGApiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        api_calls.append(request)
        if request.url.path.endswith("/sets"):
            return httpx.Response(200, json={"sets": SAMPLE_SETS})

        page = int(request.url.params.get("page", 1))
        if page > 1:
            return httpx.Response(200, json={"cards": []})

        cards = SAMPLE_CARDS
        name = request.url.params.get("name")
        if name:
            cards = [c for c in cards if name.lower() in c["name"].lower()]
        subtypes = request.url.params.get("subtypes")
        if subtypes:
            wanted = {s.strip().lower() for s in subtypes.split(",")}
            cards = [c for c in cards if wanted <= {s.lower() for s in c["subtypes"]}]
        return httpx.Response(200, json={"cards": cards})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url=settings.mtg_api_base_url)
    return MTGApiClient(settings=settings, client=http_client)


@pytest.fixture
def tool_context(
    rules_index: RulesIndex, mtg_client: MTGApiClient, settings: Settings
) -> ToolContext:
    return ToolContext(rules_index=rules_index, mtg_client=mtg_client, settings=settings)


# --------------------------------------------------------------------------
# Doble del cliente de Anthropic
# --------------------------------------------------------------------------
class FakeBlock:
    """Imita un content block de la Messages API (tiene .type y atributos)."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def text_block(text: str) -> FakeBlock:
    return FakeBlock(type="text", text=text)


def tool_use_block(tool_id: str, name: str, payload: dict[str, Any]) -> FakeBlock:
    return FakeBlock(type="tool_use", id=tool_id, name=name, input=payload)


class FakeResponse:
    def __init__(self, content: list[FakeBlock], stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        # Copia del historial: el agente muta la lista despues de la llamada y
        # sin esta instantanea las aserciones verian el estado final, no el de
        # este turno.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if not self._responses:
            raise AssertionError("El agente pidio mas respuestas de las programadas.")
        return self._responses.pop(0)


class FakeLLM:
    """Devuelve una secuencia de respuestas preprogramada, en orden."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.messages = FakeMessages(responses)


@pytest.fixture
def make_agent(tool_context: ToolContext, settings: Settings):
    def _make(responses: list[FakeResponse], **overrides: Any) -> MTGAgent:
        return MTGAgent(
            llm=FakeLLM(responses),
            tool_context=tool_context,
            settings=settings.model_copy(update=overrides),
        )

    return _make
