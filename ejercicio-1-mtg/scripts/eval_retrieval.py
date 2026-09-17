#!/usr/bin/env python
"""Evalua la recuperacion contra el mini golden set.

    python -m mtg_assistant.rag.ingest data/raw/reglamento.pdf
    python scripts/eval_retrieval.py

Mide `recall@k`: de las reglas que deberian citarse, cuantas aparecen entre las
k recuperadas. Es la metrica que aisla los fallos del RAG de los del modelo, y
la que se usa como puerta antes de promover un indice nuevo (ver
docs/01-arquitectura-produccion.md, seccion 6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mtg_assistant.config import get_settings
from mtg_assistant.rag.index import RulesIndex

GOLDEN_SET = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden_set.json"


def evaluate(index: RulesIndex, cases: list[dict], k: int = 6) -> tuple[float, list[str]]:
    aciertos = 0
    fallos: list[str] = []
    for case in cases:
        recuperadas = {hit.chunk.rule_number for hit in index.search(case["query"], top_k=k)}
        if recuperadas & set(case["expected"]):
            aciertos += 1
        else:
            fallos.append(f"{case['query']}  (esperaba {case['expected']})")
    return aciertos / len(cases), fallos


def main() -> int:
    settings = get_settings()
    try:
        index = RulesIndex.load(settings.rules_index_path)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    cases = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    print(f"corpus: {len(index)} fragmentos | casos: {len(cases)}\n")
    for k in (3, 6, 10):
        recall, fallos = evaluate(index, cases, k=k)
        print(f"recall@{k}: {recall:.0%}  ({len(cases) - len(fallos)}/{len(cases)})")
        if k == 6 and fallos:
            print("\n  sin acierto en top-6:")
            for fallo in fallos:
                print(f"    - {fallo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
