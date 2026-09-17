"""API HTTP del asistente.

    uvicorn mtg_assistant.api:app --reload --port 8000
"""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from mtg_assistant.agent import MTGAgent
from mtg_assistant.clients.mtg_api import MTGApiError
from mtg_assistant.factory import build_agent, load_rules_index
from mtg_assistant.models import ChatRequest, ChatResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Asistente MTG",
    version="0.1.0",
    description="Chatbot de reglas, cartas e interacciones de Magic: The Gathering.",
)

# La demo sirve la UI de Streamlit en otro puerto.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@lru_cache(maxsize=1)
def get_agent() -> MTGAgent:
    """El agente es un singleton perezoso: se crea en la primera peticion."""
    return build_agent()


@app.get("/health")
def health() -> dict[str, object]:
    try:
        chunks = len(load_rules_index())
    except FileNotFoundError:
        return {"status": "degraded", "reason": "indice de reglas no construido"}
    return {"status": "ok", "rule_chunks": chunks}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, agent: MTGAgent = Depends(get_agent)) -> ChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="El mensaje no puede estar vacio.")
    try:
        return agent.chat(request.message, conversation_id=request.conversation_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MTGApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/conversations/{conversation_id}", status_code=204)
def reset_conversation(
    conversation_id: str, agent: MTGAgent = Depends(get_agent)
) -> None:
    agent.reset(conversation_id)
