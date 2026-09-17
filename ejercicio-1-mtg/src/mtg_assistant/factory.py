"""Cableado de dependencias: un solo sitio donde se construye todo."""

from __future__ import annotations

from functools import lru_cache

from mtg_assistant.agent import MTGAgent
from mtg_assistant.clients.llm import build_llm_client
from mtg_assistant.clients.mtg_api import MTGApiClient
from mtg_assistant.config import Settings, get_settings
from mtg_assistant.rag.index import RulesIndex
from mtg_assistant.tools import ToolContext


@lru_cache(maxsize=1)
def load_rules_index() -> RulesIndex:
    """El indice se carga una vez por proceso (es inmutable en caliente)."""
    return RulesIndex.load(get_settings().rules_index_path)


def build_agent(settings: Settings | None = None) -> MTGAgent:
    """Construye el agente con el cliente LLM del proveedor configurado.

    Las credenciales se resuelven desde el entorno -- la cadena estandar de AWS
    para Bedrock, `ANTHROPIC_API_KEY` para la API de primera parte -- y nunca se
    pasan por codigo.
    """
    settings = settings or get_settings()
    context = ToolContext(
        rules_index=load_rules_index(),
        mtg_client=MTGApiClient(settings=settings),
        settings=settings,
    )
    return MTGAgent(
        llm=build_llm_client(settings), tool_context=context, settings=settings
    )
