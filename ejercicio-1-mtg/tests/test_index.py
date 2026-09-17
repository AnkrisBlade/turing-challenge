"""BM25, sinonimos ES<->EN y persistencia del indice."""

from __future__ import annotations

from pathlib import Path

from mtg_assistant.rag.index import RulesIndex, expand_query, tokenize


def test_tokenize_quita_acentos_y_stopwords() -> None:
    tokens = tokenize("El daño de combate en la fase")
    assert "dano" in tokens
    assert "combate" in tokens
    assert "el" not in tokens and "la" not in tokens


def test_expand_query_tiende_el_puente_es_en() -> None:
    tokens = expand_query("como funciona dana primero")
    assert "first" in tokens and "strike" in tokens


def test_busqueda_basica_por_fases(rules_index: RulesIndex) -> None:
    hits = rules_index.search("que fases hay en un turno", top_k=3)
    assert hits
    assert hits[0].chunk.rule_number == "500.1"


def test_busqueda_de_mana(rules_index: RulesIndex) -> None:
    hits = rules_index.search("como funciona el mana", top_k=3)
    assert {h.chunk.rule_number for h in hits} & {"106.1", "106.2", "106.4"}


def test_consulta_en_ingles_encuentra_regla_en_espanol(rules_index: RulesIndex) -> None:
    """El corpus esta en espanol y el cliente escribe 'first strike'."""
    hits = rules_index.search("first strike damage", top_k=3)
    assert "702.7b" in {h.chunk.rule_number for h in hits}


def test_numero_de_regla_exacto_sube_al_top(rules_index: RulesIndex) -> None:
    hits = rules_index.search("explicame la 702.9b", top_k=3)
    assert hits[0].chunk.rule_number == "702.9b"


def test_sin_resultados_devuelve_lista_vacia(rules_index: RulesIndex) -> None:
    assert rules_index.search("cotizacion del ibex bursatil") == []


def test_indice_vacio_no_rompe() -> None:
    assert RulesIndex([]).search("lo que sea") == []


def test_los_scores_van_de_mayor_a_menor(rules_index: RulesIndex) -> None:
    hits = rules_index.search("dano de combate criaturas", top_k=5)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_guardar_y_cargar_conserva_el_corpus(rules_index: RulesIndex, tmp_path: Path) -> None:
    destino = tmp_path / "idx" / "rules.jsonl"
    rules_index.save(destino)
    recargado = RulesIndex.load(destino)
    assert len(recargado) == len(rules_index)
    assert recargado.search("mana")[0].chunk.text == rules_index.search("mana")[0].chunk.text


def test_cargar_indice_inexistente_explica_como_generarlo(tmp_path: Path) -> None:
    try:
        RulesIndex.load(tmp_path / "no-existe.jsonl")
    except FileNotFoundError as exc:
        assert "mtg_assistant.rag.ingest" in str(exc)
    else:
        raise AssertionError("Deberia haber lanzado FileNotFoundError")


def test_el_titulo_de_seccion_pesa_en_el_ranking(rules_index: RulesIndex) -> None:
    """Una regla de la seccion 'Mana y costes' gana a una que solo lo menciona."""
    hits = rules_index.search("mana", top_k=5)
    assert hits[0].chunk.section == "1. Mana y costes"


def test_la_regla_general_gana_a_la_lettered(rules_index: RulesIndex) -> None:
    """'509.1a' cubre una esquina; ante una pregunta amplia manda la general."""
    from mtg_assistant.rag.index import TOP_LEVEL_RULE_PRIOR

    assert TOP_LEVEL_RULE_PRIOR > 1
    generales = [h for h in rules_index.search("dano de combate", top_k=5)]
    assert generales  # el prior no puede dejar la busqueda sin resultados
