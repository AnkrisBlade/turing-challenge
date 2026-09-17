"""Herramienta de consulta al reglamento (RAG lexico)."""

from __future__ import annotations

from typing import Any

from mtg_assistant.models import Citation
from mtg_assistant.tools.base import Tool, ToolContext, ToolResult

MAX_TOP_K = 10


def search_rules(context: ToolContext, query: str, top_k: int | None = None) -> ToolResult:
    query = (query or "").strip()
    if not query:
        return ToolResult.error("La consulta de reglas no puede estar vacia.")

    # Si el modelo no pide un numero concreto manda la configuracion del
    # servidor (`MTG_RULES_TOP_K`); lo que si pida se acota al maximo.
    if top_k is None:
        top_k = context.settings.rules_top_k
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    hits = context.rules_index.search(query, top_k=top_k)
    if not hits:
        return ToolResult(
            content=(
                "Sin resultados en el reglamento para esa consulta. "
                "Dilo explicitamente en la respuesta en lugar de improvisar una regla."
            ),
            summary=f"0 fragmentos para '{query}'",
        )

    blocks: list[str] = []
    citations: list[Citation] = []
    for hit in hits:
        chunk = hit.chunk
        label = f"regla {chunk.rule_number}" if chunk.rule_number else f"pag. {chunk.page}"
        header = f"[{label}]"
        if chunk.section:
            header += f" ({chunk.section})"
        blocks.append(f"{header}\n{chunk.text}")
        citations.append(
            Citation(kind="rule", label=label, detail=chunk.section or chunk.chunk_id)
        )

    return ToolResult(
        content="\n\n---\n\n".join(blocks),
        summary=f"{len(hits)} fragmentos para '{query}'",
        citations=citations,
    )


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Consulta en lenguaje natural sobre las reglas. Incluye los terminos "
                "de juego relevantes (p.ej. 'dana primero paso de dano de combate'). "
                "Tambien acepta un numero de regla exacto como '509.1a'."
            ),
        },
        "top_k": {
            "type": "integer",
            "description": (
                "Cuantos fragmentos recuperar (1-10). Si se omite, manda el "
                "valor configurado en el servidor."
            ),
            "minimum": 1,
            "maximum": MAX_TOP_K,
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

TOOL = Tool(
    name="search_rules",
    description=(
        "Busca fragmentos literales del reglamento oficial de Magic: The Gathering. "
        "Usala SIEMPRE antes de afirmar como funciona una regla o una interaccion "
        "entre cartas: la respuesta al cliente debe apoyarse en el texto recuperado. "
        "Puedes llamarla varias veces con consultas distintas para cubrir cada parte "
        "de una interaccion compleja."
    ),
    input_schema=SCHEMA,
    handler=search_rules,
)
