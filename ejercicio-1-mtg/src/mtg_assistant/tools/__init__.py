"""Registro de herramientas disponibles para el agente."""

from __future__ import annotations

from mtg_assistant.tools.base import Tool, ToolContext
from mtg_assistant.tools.cards import GET_CARD_TOOL, LIST_SETS_TOOL, SEARCH_TOOL
from mtg_assistant.tools.designer import TOOL as DESIGN_TOOL
from mtg_assistant.tools.rules import TOOL as RULES_TOOL

# El orden es estable a proposito: la definicion de tools forma parte del
# prefijo cacheable de la peticion (ver docs/02-decisiones-tecnicas.md).
ALL_TOOLS: tuple[Tool, ...] = (
    RULES_TOOL,
    GET_CARD_TOOL,
    SEARCH_TOOL,
    LIST_SETS_TOOL,
    DESIGN_TOOL,
)


def build_registry(tools: tuple[Tool, ...] = ALL_TOOLS) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}


__all__ = ["ALL_TOOLS", "Tool", "ToolContext", "build_registry"]
