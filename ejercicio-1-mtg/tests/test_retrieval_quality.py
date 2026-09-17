"""Calidad de recuperacion contra el mini golden set.

Se salta si no hay indice construido: el reglamento del cliente no se versiona
(copyright de Wizards of the Coast), asi que en CI este fichero no corre. En
local, tras `python -m mtg_assistant.rag.ingest data/raw/<reglamento>.pdf`, es
la puerta que decide si un cambio en el RAG mejora o empeora.

    python scripts/eval_retrieval.py   # mismo calculo, con detalle por caso
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mtg_assistant.config import get_settings
from mtg_assistant.rag.index import RulesIndex

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

GOLDEN_SET = Path(__file__).parent / "fixtures" / "golden_set.json"
# Linea base medida sobre las Comprehensive Rules (20260417): 62 % en top-6.
# Se fija algo por debajo para no romper con otra edicion del reglamento.
MIN_RECALL_AT_6 = 0.55


@pytest.fixture(scope="module")
def indice_real() -> RulesIndex:
    ruta = get_settings().rules_index_path
    if not ruta.exists():
        pytest.skip(f"no hay indice en {ruta}; ejecuta la ingesta primero")
    return RulesIndex.load(ruta)


def test_recall_at_6_sobre_el_golden_set(indice_real: RulesIndex) -> None:
    from eval_retrieval import evaluate

    casos = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    recall, fallos = evaluate(indice_real, casos, k=6)
    assert recall >= MIN_RECALL_AT_6, (
        f"recall@6={recall:.0%} por debajo de {MIN_RECALL_AT_6:.0%}. Sin acierto:\n  "
        + "\n  ".join(fallos)
    )


def test_una_referencia_explicita_a_una_regla_la_recupera(indice_real: RulesIndex) -> None:
    hits = indice_real.search("Explicame la regla 702.7b", top_k=3)
    assert hits[0].chunk.rule_number == "702.7b"
