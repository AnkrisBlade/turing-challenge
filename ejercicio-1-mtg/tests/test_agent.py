"""Bucle agentico: herramientas, memoria, trazas y caminos de fallo."""

from __future__ import annotations

from conftest import FakeResponse, text_block, tool_use_block

from mtg_assistant.agent import ConversationStore


def _final(text: str) -> FakeResponse:
    return FakeResponse([text_block(text)], stop_reason="end_turn")


def test_una_pregunta_sin_herramientas_responde_directo(make_agent) -> None:
    agent = make_agent([_final("Hola, en que puedo ayudarte?")])
    response = agent.chat("hola")
    assert response.answer.startswith("Hola")
    assert response.trace == []


def test_el_agente_ejecuta_la_herramienta_y_vuelve_al_modelo(make_agent) -> None:
    agent = make_agent(
        [
            FakeResponse(
                [tool_use_block("t1", "search_rules", {"query": "fases del turno"})],
                stop_reason="tool_use",
            ),
            _final("Un turno tiene cinco fases. Base: regla 500.1"),
        ]
    )
    response = agent.chat("Que fases hay en un turno?")

    assert len(response.trace) == 1
    assert response.trace[0].tool == "search_rules" and response.trace[0].ok
    assert any(c.label == "regla 500.1" for c in response.citations)
    assert "cinco fases" in response.answer


def test_varias_herramientas_en_un_turno_viajan_en_un_solo_mensaje(make_agent) -> None:
    agent = make_agent(
        [
            FakeResponse(
                [
                    tool_use_block("t1", "get_card", {"name": "Wojek Halberdiers"}),
                    tool_use_block("t2", "search_rules", {"query": "dana primero"}),
                ],
                stop_reason="tool_use",
            ),
            _final("Respuesta con las dos fuentes."),
        ]
    )
    response = agent.chat("Como interactua Wojek Halberdiers con dana primero?")

    assert [t.tool for t in response.trace] == ["get_card", "search_rules"]
    segunda_llamada = agent.llm.messages.calls[1]
    resultados = segunda_llamada["messages"][-1]["content"]
    assert len(resultados) == 2
    assert {b["tool_use_id"] for b in resultados} == {"t1", "t2"}


def test_una_herramienta_desconocida_no_tumba_la_conversacion(make_agent) -> None:
    agent = make_agent(
        [
            FakeResponse(
                [tool_use_block("t1", "buscar_en_google", {"q": "x"})],
                stop_reason="tool_use",
            ),
            _final("No tengo esa capacidad, pero puedo consultar el reglamento."),
        ]
    )
    response = agent.chat("busca en google")
    assert response.trace[0].ok is False
    resultado = agent.llm.messages.calls[1]["messages"][-1]["content"][0]
    assert resultado["is_error"] is True


def test_argumentos_invalidos_vuelven_como_tool_result_de_error(make_agent) -> None:
    agent = make_agent(
        [
            FakeResponse(
                [tool_use_block("t1", "search_rules", {"parametro_raro": 1})],
                stop_reason="tool_use",
            ),
            _final("Reformulo la consulta."),
        ]
    )
    response = agent.chat("algo")
    assert response.trace[0].ok is False
    assert "Argumentos invalidos" in response.trace[0].summary


def test_el_input_serializado_como_json_se_parsea(make_agent) -> None:
    agent = make_agent(
        [
            FakeResponse(
                [tool_use_block("t1", "search_rules", '{"query": "mana"}')],
                stop_reason="tool_use",
            ),
            _final("El mana es el recurso del juego. Base: regla 106.1"),
        ]
    )
    response = agent.chat("como funciona el mana")
    assert response.trace[0].ok


def test_la_carta_custom_llega_al_response(make_agent) -> None:
    agent = make_agent(
        [
            FakeResponse(
                [
                    tool_use_block(
                        "t1",
                        "design_custom_card",
                        {
                            "name": "Han Solo, Contrabandista",
                            "mana_cost": "{1}{R}{W}",
                            "type_line": "Legendary Creature - Human Rogue",
                            "rules_text": "Dana primero.",
                            "power": "3",
                            "toughness": "2",
                            "colors": ["R", "W"],
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            _final("Aqui tienes tu carta."),
        ]
    )
    response = agent.chat("quiero una carta de Han Solo blanca-roja con dana primero")
    assert response.custom_card is not None
    assert response.custom_card.name == "Han Solo, Contrabandista"


def test_el_limite_de_turnos_corta_el_bucle(make_agent) -> None:
    bucle = [
        FakeResponse(
            [tool_use_block(f"t{i}", "search_rules", {"query": "dano"})],
            stop_reason="tool_use",
        )
        for i in range(3)
    ]
    agent = make_agent(bucle, max_tool_turns=3)
    response = agent.chat("pregunta que no converge")
    assert "juez" in response.answer
    assert len(response.trace) == 3


def test_un_refusal_se_responde_sin_romper(make_agent) -> None:
    agent = make_agent([FakeResponse([], stop_reason="refusal")])
    response = agent.chat("algo que el modelo rechaza")
    assert "No puedo ayudarte" in response.answer


def test_la_conversacion_mantiene_el_hilo(make_agent) -> None:
    agent = make_agent([_final("Primera"), _final("Segunda")])
    primera = agent.chat("Que es el mana?")
    segunda = agent.chat("Y como se vacia?", conversation_id=primera.conversation_id)

    assert segunda.conversation_id == primera.conversation_id
    historial = agent.llm.messages.calls[1]["messages"]
    assert [m["role"] for m in historial] == ["user", "assistant", "user"]
    assert historial[0]["content"] == "Que es el mana?"


def test_conversaciones_distintas_no_se_mezclan(make_agent) -> None:
    agent = make_agent([_final("A"), _final("B")])
    agent.chat("hola", conversation_id="conv-a")
    agent.chat("hola", conversation_id="conv-b")
    assert len(agent.llm.messages.calls[1]["messages"]) == 1


def test_reset_borra_el_historial(make_agent) -> None:
    agent = make_agent([_final("A"), _final("B")])
    agent.chat("hola", conversation_id="conv-a")
    agent.reset("conv-a")
    agent.chat("hola de nuevo", conversation_id="conv-a")
    assert len(agent.llm.messages.calls[1]["messages"]) == 1


def test_el_prompt_de_sistema_es_cacheable(make_agent) -> None:
    agent = make_agent([_final("ok")])
    agent.chat("hola")
    system = agent.llm.messages.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_las_tools_van_en_orden_estable(make_agent) -> None:
    agent = make_agent([_final("a"), _final("b")])
    agent.chat("uno")
    agent.chat("dos")
    nombres = lambda call: [t["name"] for t in call["tools"]]  # noqa: E731
    assert nombres(agent.llm.messages.calls[0]) == nombres(agent.llm.messages.calls[1])


# --- memoria --------------------------------------------------------------
def test_el_recorte_no_parte_un_par_tool_use_tool_result() -> None:
    store = ConversationStore(max_messages=3)
    mensajes = [
        {"role": "user", "content": "pregunta 1"},
        {"role": "assistant", "content": "respuesta 1"},
        {"role": "user", "content": "pregunta 2"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1"}]},
        {"role": "assistant", "content": "respuesta 2"},
    ]
    store.save("c", mensajes)
    recortado = store.get("c")

    # Empieza en un turno de usuario real, nunca en un tool_result huerfano.
    primero = recortado[0]
    assert primero["role"] == "user"
    assert isinstance(primero["content"], str)


def test_historial_corto_no_se_toca() -> None:
    store = ConversationStore(max_messages=10)
    mensajes = [{"role": "user", "content": "hola"}]
    store.save("c", mensajes)
    assert store.get("c") == mensajes


def test_las_cartas_encontradas_viajan_en_la_respuesta(make_agent) -> None:
    """La UI pinta las imagenes de las cartas, y el texto no puede darlas."""
    agent = make_agent(
        [
            FakeResponse(
                [tool_use_block("t1", "get_card", {"name": "Savannah Lions"})],
                stop_reason="tool_use",
            ),
            _final("Savannah Lions es un 2/1 por {W}. Base: Savannah Lions"),
        ]
    )
    response = agent.chat("hablame de Savannah Lions")

    assert [c.name for c in response.cards] == ["Savannah Lions"]
    assert response.cards[0].image_url == "https://example.test/lions.png"


def test_si_la_busqueda_no_trae_imagen_gana_la_ficha_con_arte() -> None:
    """Alpha a menudo no trae imageUrl; la impresion posterior si."""
    from mtg_assistant.agent.loop import _TurnAccumulator

    acc = _TurnAccumulator()
    acc.absorb_payload(
        {"cards": [{"name": "Lightning Bolt", "set_name": "Limited Edition Alpha"}]}
    )
    acc.absorb_payload(
        {
            "cards": [
                {
                    "name": "Lightning Bolt",
                    "set_name": "Magic 2010",
                    "image_url": "https://gatherer.wizards.com/bolt.png",
                }
            ]
        }
    )

    assert len(acc.cards) == 1
    assert acc.cards[0].set_name == "Magic 2010"
    assert acc.cards[0].image_url == "https://gatherer.wizards.com/bolt.png"


def test_no_se_sustituye_una_imagen_por_una_impresion_sin_arte() -> None:
    from mtg_assistant.agent.loop import _TurnAccumulator

    acc = _TurnAccumulator()
    acc.absorb_payload(
        {
            "cards": [
                {
                    "name": "Lightning Bolt",
                    "set_name": "Magic 2010",
                    "image_url": "https://gatherer.wizards.com/bolt.png",
                }
            ]
        }
    )
    acc.absorb_payload(
        {"cards": [{"name": "Lightning Bolt", "set_name": "Limited Edition Alpha"}]}
    )

    assert acc.cards[0].set_name == "Magic 2010"
    assert acc.cards[0].image_url == "https://gatherer.wizards.com/bolt.png"


def test_varias_impresiones_en_una_busqueda_se_quedan_con_la_que_tiene_imagen(
    make_agent,
) -> None:
    """La API de cartas devuelve una ficha por impresion; la UI solo pinta una."""
    agent = make_agent(
        [
            FakeResponse(
                [tool_use_block("t1", "search_cards", {"name": "Lightning Bolt"})],
                stop_reason="tool_use",
            ),
            _final("Lightning Bolt hace 3 de dano. Base: Lightning Bolt"),
        ]
    )
    response = agent.chat("busca Lightning Bolt")

    assert [c.name for c in response.cards] == ["Lightning Bolt"]
    assert response.cards[0].image_url
    assert "gatherer.wizards.com" in response.cards[0].image_url


def test_get_card_despues_de_buscar_no_quita_la_imagen(make_agent) -> None:
    """La ficha exacta suele ser la impresion mas antigua, a menudo sin arte."""
    agent = make_agent(
        [
            FakeResponse(
                [
                    tool_use_block("t1", "search_cards", {"name": "Lightning Bolt"}),
                    tool_use_block("t2", "get_card", {"name": "Lightning Bolt"}),
                ],
                stop_reason="tool_use",
            ),
            _final("Lightning Bolt hace 3 de dano. Base: Lightning Bolt"),
        ]
    )
    response = agent.chat("como funciona Lightning Bolt")

    assert [c.name for c in response.cards] == ["Lightning Bolt"]
    assert response.cards[0].image_url
    assert "gatherer.wizards.com" in response.cards[0].image_url
