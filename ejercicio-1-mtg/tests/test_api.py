"""API HTTP: contrato con la UI, sin tocar Anthropic ni la red."""

from __future__ import annotations

import pytest
from conftest import FakeResponse, text_block, tool_use_block
from fastapi.testclient import TestClient

from mtg_assistant import api as api_module


@pytest.fixture
def client(make_agent):
    agent = make_agent(
        [
            FakeResponse(
                [tool_use_block("t1", "search_rules", {"query": "fases del turno"})],
                stop_reason="tool_use",
            ),
            FakeResponse(
                [text_block("Un turno tiene cinco fases. Base: regla 500.1")],
                stop_reason="end_turn",
            ),
            FakeResponse([text_block("Segunda respuesta.")], stop_reason="end_turn"),
        ]
    )
    api_module.app.dependency_overrides[api_module.get_agent] = lambda: agent
    yield TestClient(api_module.app), agent
    api_module.app.dependency_overrides.clear()


def test_chat_devuelve_respuesta_citas_y_traza(client) -> None:
    http, _ = client
    response = http.post("/chat", json={"message": "Que fases hay en un turno?"})
    assert response.status_code == 200

    body = response.json()
    assert "cinco fases" in body["answer"]
    assert body["conversation_id"]
    assert any(c["label"] == "regla 500.1" for c in body["citations"])
    assert body["trace"][0]["tool"] == "search_rules"


def test_el_conversation_id_se_reutiliza(client) -> None:
    http, agent = client
    primera = http.post("/chat", json={"message": "Que fases hay?"}).json()
    segunda = http.post(
        "/chat",
        json={"message": "Y luego?", "conversation_id": primera["conversation_id"]},
    ).json()
    assert segunda["conversation_id"] == primera["conversation_id"]
    assert len(agent.llm.messages.calls[-1]["messages"]) > 1


def test_mensaje_vacio_es_422(client) -> None:
    http, _ = client
    assert http.post("/chat", json={"message": "   "}).status_code == 422


def test_borrar_conversacion_devuelve_204(client) -> None:
    http, _ = client
    body = http.post("/chat", json={"message": "Que fases hay?"}).json()
    assert http.delete(f"/conversations/{body['conversation_id']}").status_code == 204


def test_health_avisa_si_no_hay_indice(monkeypatch) -> None:
    def sin_indice():
        raise FileNotFoundError("no index")

    monkeypatch.setattr(api_module, "load_rules_index", sin_indice)
    body = TestClient(api_module.app).get("/health").json()
    assert body["status"] == "degraded"


def test_health_ok_reporta_el_numero_de_fragmentos(monkeypatch, rules_index) -> None:
    monkeypatch.setattr(api_module, "load_rules_index", lambda: rules_index)
    body = TestClient(api_module.app).get("/health").json()
    assert body["status"] == "ok" and body["rule_chunks"] == len(rules_index)
