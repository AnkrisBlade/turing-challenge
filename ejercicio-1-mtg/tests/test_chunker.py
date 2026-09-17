"""El troceado decide de que se puede citar: si falla, la respuesta no tiene base."""

from __future__ import annotations

from mtg_assistant.rag.chunker import chunk_document, detect_mode


def test_detecta_modo_numerado(rules_text: str) -> None:
    assert detect_mode(rules_text) == "numbered"


def test_texto_sin_numeracion_cae_a_parrafos() -> None:
    texto = (
        "Bienvenido a Magic. Este documento explica lo basico del juego "
        "para jugadores que empiezan hoy mismo.\n\n"
        "Cada jugador empieza con veinte puntos de vida y un mazo propio "
        "de al menos sesenta cartas distintas.\n\n"
        "Ganas la partida cuando tu oponente llega a cero puntos de vida "
        "o no puede robar una carta de su biblioteca."
    )
    assert detect_mode(texto) == "paragraph"
    chunks = chunk_document(texto)
    assert chunks
    assert all(c.rule_number is None for c in chunks)


def test_un_chunk_por_regla_con_id_estable(rules_text: str) -> None:
    chunks = chunk_document(rules_text)
    numeros = [c.rule_number for c in chunks]
    assert "702.7b" in numeros
    assert "106.4" in numeros
    regla = next(c for c in chunks if c.rule_number == "702.7b")
    assert regla.chunk_id == "rule-702.7b"


def test_el_chunk_conserva_pagina_y_seccion(rules_text: str) -> None:
    chunks = chunk_document(rules_text)
    regla = next(c for c in chunks if c.rule_number == "106.1")
    assert regla.page == 2
    assert regla.section == "1. Mana y costes"


def test_las_lineas_continuadas_se_unen_en_el_mismo_chunk(rules_text: str) -> None:
    regla = next(c for c in chunk_document(rules_text) if c.rule_number == "500.1")
    # La regla ocupa dos lineas en el fuente; debe quedar en un solo texto.
    assert "comienzo" in regla.text and "final" in regla.text
    assert "\n" not in regla.text


def test_los_marcadores_de_pagina_no_acaban_en_el_texto(rules_text: str) -> None:
    for chunk in chunk_document(rules_text):
        assert "<<<PAGE" not in chunk.text
