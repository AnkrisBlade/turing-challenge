"""Contrato comun de las herramientas del agente.

Cada herramienta es un objeto con: esquema JSON (lo que ve el modelo), un
handler puro sobre un `ToolContext` inyectado, y un resultado que separa tres
cosas distintas que suelen mezclarse:

* `content`   -> lo que vuelve al modelo como `tool_result`.
* `citations` -> lo que se le ensena al usuario como respaldo.
* `payload`   -> datos estructurados para la UI (imagenes, carta custom...).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mtg_assistant.clients.mtg_api import MTGApiClient
from mtg_assistant.config import Settings
from mtg_assistant.models import Citation
from mtg_assistant.rag.index import RulesIndex


@dataclass
class ToolContext:
    """Dependencias que las herramientas reciben; nunca las construyen ellas."""

    rules_index: RulesIndex
    mtg_client: MTGApiClient
    settings: Settings


@dataclass
class ToolResult:
    content: str
    ok: bool = True
    summary: str = ""
    citations: list[Citation] = field(default_factory=list)
    payload: dict[str, Any] | None = None

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls(content=f"ERROR: {message}", ok=False, summary=message)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., ToolResult]

    def to_api_schema(self) -> dict[str, Any]:
        """Definicion tal y como la espera la Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
