"""Bucle agentico: modelo -> herramientas -> modelo, hasta respuesta final.

Se usa el bucle manual de la Messages API en lugar del tool runner del SDK por
tres razones, todas visibles en los tests:

* El cliente LLM se inyecta, asi que la suite corre sin red ni API key.
* Necesitamos la traza de cada llamada a herramienta para ensenarsela al
  usuario ("base de referencia") y para observabilidad.
* Evita depender de una API beta en el camino critico de produccion.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from mtg_assistant.agent.prompts import SYSTEM_PROMPT
from mtg_assistant.clients.llm import capabilities_for
from mtg_assistant.config import Settings, get_settings
from mtg_assistant.models import Card, ChatResponse, Citation, CustomCard, ToolCallTrace
from mtg_assistant.tools import ToolContext, build_registry

logger = logging.getLogger(__name__)

# Cuantos turnos (user + assistant) se conservan por conversacion.
MAX_HISTORY_MESSAGES = 40


class LLMClient(Protocol):
    """Lo minimo que el agente necesita de `anthropic.Anthropic`."""

    messages: Any


class ConversationStore:
    """Memoria de conversacion en proceso.

    Suficiente para la demo. En produccion esto es Redis con TTL: ver
    `docs/01-arquitectura-produccion.md`, seccion Estado.
    """

    def __init__(self, max_messages: int = MAX_HISTORY_MESSAGES) -> None:
        self._conversations: dict[str, list[dict[str, Any]]] = {}
        self._max_messages = max_messages

    def get(self, conversation_id: str) -> list[dict[str, Any]]:
        return list(self._conversations.get(conversation_id, []))

    def save(self, conversation_id: str, messages: list[dict[str, Any]]) -> None:
        self._conversations[conversation_id] = self._trim(messages)

    def reset(self, conversation_id: str) -> None:
        self._conversations.pop(conversation_id, None)

    def _trim(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Recorta el historial sin partir un par tool_use / tool_result.

        Solo se corta en el comienzo de un turno de usuario real. Si dentro del
        limite no hay ninguno -- un turno largo con muchas herramientas --, se
        conserva el ultimo turno entero aunque exceda el limite: un historial
        valido y algo mas largo es preferible a uno truncado que la API rechaza.
        """
        if len(messages) <= self._max_messages:
            return list(messages)

        boundaries = [i for i, message in enumerate(messages) if _starts_a_turn(message)]
        if not boundaries:
            return list(messages)

        floor = len(messages) - self._max_messages
        start = next((i for i in boundaries if i >= floor), boundaries[-1])
        return list(messages[start:])


def _starts_a_turn(message: dict[str, Any]) -> bool:
    """True si el mensaje es un turno de usuario real (no un tool_result)."""
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, str):
        return True
    return not any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content or []
    )


@dataclass
class _TurnAccumulator:
    """Acumula lo que hay que devolver al usuario a lo largo del bucle."""

    trace: list[ToolCallTrace] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    custom_card: CustomCard | None = None

    def add_citations(self, citations: list[Citation]) -> None:
        seen = {(c.kind, c.label) for c in self.citations}
        for citation in citations:
            key = (citation.kind, citation.label)
            if key not in seen:
                seen.add(key)
                self.citations.append(citation)

    def absorb_payload(self, payload: dict[str, Any] | None) -> None:
        """Recoge los datos estructurados que la UI necesita y el texto no da.

        Una misma carta puede salir en varias herramientas del mismo turno
        (una busqueda y luego su ficha), asi que se deduplica por nombre.
        La API devuelve una ficha por impresion y las viejas a menudo no
        traen `image_url`: si ya teniamos la carta sin imagen y llega una
        que si la trae, nos quedamos con esa.
        """
        if not payload:
            return
        if "custom_card" in payload:
            self.custom_card = CustomCard(**payload["custom_card"])
        index_by_name = {card.name: i for i, card in enumerate(self.cards)}
        for raw in payload.get("cards", []):
            card = Card(**raw)
            index = index_by_name.get(card.name)
            if index is None:
                index_by_name[card.name] = len(self.cards)
                self.cards.append(card)
                continue
            if not self.cards[index].image_url and card.image_url:
                self.cards[index] = card


class MTGAgent:
    def __init__(
        self,
        llm: LLMClient,
        tool_context: ToolContext,
        settings: Settings | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        self.llm = llm
        self.tool_context = tool_context
        self.settings = settings or get_settings()
        self.registry = build_registry()
        self.store = store or ConversationStore()
        # `thinking` y `output_config.effort` solo viajan si el modelo los
        # admite: Haiku 4.5 devuelve 400 ante cualquiera de los dos.
        self.capabilities = capabilities_for(self.settings.model)

    # -- API publica ------------------------------------------------------
    def chat(self, message: str, conversation_id: str | None = None) -> ChatResponse:
        conversation_id = conversation_id or uuid.uuid4().hex
        messages = self.store.get(conversation_id)
        messages.append({"role": "user", "content": message})

        acc = _TurnAccumulator()
        answer = ""

        for _turn in range(self.settings.max_tool_turns):
            response = self._call_model(messages)

            if response.stop_reason == "refusal":
                answer = (
                    "No puedo ayudarte con esa peticion. Si es una duda de reglas, "
                    "reformulala y lo intento de nuevo."
                )
                break

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                answer = _extract_text(response.content)
                break

            tool_results = self._run_tools(response.content, acc)
            messages.append({"role": "user", "content": tool_results})
        else:
            logger.warning(
                "Limite de %s turnos de herramienta alcanzado", self.settings.max_tool_turns
            )
            answer = (
                "He consultado varias fuentes y sigo sin poder cerrar una respuesta "
                "fiable. Te paso con un juez para que lo revise."
            )

        self.store.save(conversation_id, messages)
        return ChatResponse(
            conversation_id=conversation_id,
            answer=answer,
            citations=acc.citations,
            trace=acc.trace,
            cards=acc.cards,
            custom_card=acc.custom_card,
        )

    def reset(self, conversation_id: str) -> None:
        self.store.reset(conversation_id)

    # -- Internos ---------------------------------------------------------
    def _call_model(self, messages: list[dict[str, Any]]) -> Any:
        return self.llm.messages.create(
            model=self.settings.model,
            max_tokens=self.settings.max_tokens,
            # Bloque estable => prefijo cacheable. El breakpoint es explicito
            # porque la integracion clasica de Bedrock rechaza el cache_control
            # de nivel superior. Ver docs/02-decisiones-tecnicas.md
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[tool.to_api_schema() for tool in self.registry.values()],
            messages=messages,
            **self.capabilities.request_extras(self.settings.effort),
        )

    def _run_tools(self, content: list[Any], acc: _TurnAccumulator) -> list[dict[str, Any]]:
        """Ejecuta todos los tool_use del turno y devuelve sus tool_result.

        Los resultados de un mismo turno viajan juntos en un unico mensaje de
        usuario: separarlos ensena al modelo a dejar de paralelizar.
        """
        results: list[dict[str, Any]] = []
        for block in content:
            if getattr(block, "type", None) != "tool_use":
                continue

            arguments = _parse_tool_input(block.input)
            tool = self.registry.get(block.name)

            # Los tres desenlaces -- herramienta que no existe, handler que
            # revienta y resultado bueno -- salen por el mismo sitio: un
            # tool_result para el modelo y una linea de traza para el usuario.
            if tool is None:
                logger.error("El modelo pidio una herramienta desconocida: %s", block.name)
                result = None
                message = f"Herramienta '{block.name}' no existe."
            else:
                try:
                    result = tool.handler(self.tool_context, **arguments)
                except TypeError as exc:
                    result = None
                    message = f"Argumentos invalidos para {block.name}: {exc}"
                except Exception as exc:  # una herramienta rota no tumba la llamada
                    logger.exception("Fallo la herramienta %s", block.name)
                    result = None
                    message = f"La herramienta {block.name} fallo: {exc}"

            if result is None:
                results.append(_tool_result(block.id, message, True))
                acc.trace.append(
                    ToolCallTrace(tool=block.name, arguments=arguments, ok=False, summary=message)
                )
                continue

            results.append(_tool_result(block.id, result.content, not result.ok))
            acc.trace.append(
                ToolCallTrace(
                    tool=block.name,
                    arguments=arguments,
                    ok=result.ok,
                    summary=result.summary or result.content[:80],
                )
            )
            acc.add_citations(result.citations)
            acc.absorb_payload(result.payload)

        return results


def _tool_result(tool_use_id: str, content: str, is_error: bool) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }
    if is_error:
        block["is_error"] = True
    return block


def _parse_tool_input(raw: Any) -> dict[str, Any]:
    """El input llega como dict; si llega serializado, se parsea con json."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_text(content: list[Any]) -> str:
    parts = [
        block.text
        for block in content
        if getattr(block, "type", None) == "text" and getattr(block, "text", "")
    ]
    return "\n".join(parts).strip()
