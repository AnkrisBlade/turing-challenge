#!/usr/bin/env python
"""Prueba de humo contra Claude y la API real de cartas.

    export $(grep -v '^#' .env | xargs)   # credenciales de AWS o de Anthropic
    python -m mtg_assistant.rag.ingest tests/fixtures/reglamento_mini.txt
    python scripts/smoke.py

Lanza las cuatro consultas del enunciado sobre la misma conversacion, para
comprobar de paso que el asistente mantiene el hilo. Gasta tokens de verdad.
"""

from __future__ import annotations

import os
import sys

PREGUNTAS = [
    "Que fases hay en un turno de juego?",
    "Como funciona el mana?",
    "Mi Wojek Halberdiers ha hecho dano con dana primero. "
    "Si lo cambio por otra criatura sin dana primero, se aplica el dano igual?",
    "Busco una carta de color blanco de coste inferior a dos que sea guerrero",
    "Quiero una carta de Han Solo, blanca-roja, que tenga dana primero",
]


def main() -> int:
    from mtg_assistant.config import get_settings
    from mtg_assistant.factory import build_agent

    settings = get_settings()
    if settings.llm_provider == "bedrock":
        # `AnthropicBedrock` tambien acepta perfiles y roles de instancia, asi
        # que solo se avisa: no se bloquea por no ver las claves en el entorno.
        if not os.getenv("AWS_ACCESS_KEY_ID"):
            print(
                "Aviso: no hay AWS_ACCESS_KEY_ID en el entorno. Se usara la cadena "
                "estandar de AWS (perfil, rol de instancia...).",
                file=sys.stderr,
            )
    elif not os.getenv("ANTHROPIC_API_KEY"):
        print("Falta ANTHROPIC_API_KEY en el entorno.", file=sys.stderr)
        return 1

    print(f"proveedor: {settings.llm_provider} | modelo: {settings.model}")
    agent = build_agent()
    conversation_id = None

    for pregunta in PREGUNTAS:
        print(f"\n{'=' * 70}\n> {pregunta}\n{'-' * 70}")
        response = agent.chat(pregunta, conversation_id=conversation_id)
        conversation_id = response.conversation_id
        print(response.answer)
        if response.trace:
            print("\n  herramientas:")
            for call in response.trace:
                estado = "ok" if call.ok else "ERROR"
                print(f"    [{estado}] {call.tool}({call.arguments}) -> {call.summary}")
        if response.custom_card:
            print(f"\n  carta custom: {response.custom_card.model_dump_json(indent=2)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
