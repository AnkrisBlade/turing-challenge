"""Indice lexico BM25 sobre los fragmentos del reglamento.

Por que BM25 y no embeddings:

* El corpus es pequeno (miles de chunks) y el vocabulario es cerrado y muy
  tecnico -- justo donde lo lexico rinde bien.
* Es deterministico: los tests comprueban rankings exactos sin red ni GPU.
* Cero dependencias y cero coste por consulta.

El puente entre "dana primero" y "first strike" lo pone `glossary.py`; el
salto a un hibrido con embeddings esta descrito en `docs/01-arquitectura-
produccion.md` y solo cambia esta clase.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from mtg_assistant.models import RuleChunk, RuleHit
from mtg_assistant.rag.glossary import SYNONYM_GROUPS, expand

K1 = 1.5
B = 0.75
# Peso extra para un chunk cuyo numero de regla aparece literal en la consulta.
RULE_NUMBER_BOOST = 5.0

# Dos correcciones sobre BM25 puro, medidas contra `tests/fixtures/golden_set.json`
# con `scripts/eval_retrieval.py` (recall@6: 38% -> 62%). Ambos valores estan en
# una meseta, no en un pico: mover el peso entre 2 y 3, o el prior entre 1,3 y
# 1,8, no cambia el resultado. Con 16 casos eso importa mas que el optimo exacto.
#
# 1. El titulo de la seccion ("106. Mana") es senal de alta precision, asi que
#    sus terminos cuentan varias veces -- una aproximacion a BM25F por campos.
SECTION_TITLE_WEIGHT = 2
# 2. En el reglamento, la regla sin sufijo de letra ("509.1") enuncia el caso
#    general y las lettered ("509.1a") cubren esquinas. Ante una pregunta amplia
#    la definitoria es casi siempre la respuesta, asi que lleva un prior.
TOP_LEVEL_RULE_PRIOR = 1.5

TOKEN_RE = re.compile(r"[a-z0-9]+")
RULE_REF_RE = re.compile(r"\b\d{3}\.\d+[a-z]?\b")
TOP_LEVEL_RULE_RE = re.compile(r"^\d{3}\.\d+$")

STOPWORDS = frozenset(
    """
    a al algo ante antes como con contra cual cuando de del desde donde dos el
    ella ellas ellos en entre era es esa ese eso esta este esto ha hace hasta
    hay la las le les lo los mas me mi mis mucho muy no nos o os otra otro para
    pero poco por porque que quien se ser si sin sobre son su sus te tiene
    todo todos tu un una uno unos y ya
    a an and are as at be but by for from has have how i if in into is it its
    of on or that the their then there these they this to was what when which
    who will with you your
    """.split()
)


def _fold(text: str) -> str:
    """Minusculas sin acentos: 'Daño' y 'dano' deben ser el mismo token."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(_fold(text)) if t not in STOPWORDS and len(t) > 1]


def expand_query(text: str) -> list[str]:
    """Tokeniza y anade sinonimos ES<->EN, sin duplicados y en orden estable."""
    folded = _fold(text)
    tokens = tokenize(text)

    extra: list[str] = []
    for group in _matching_groups(folded, tokens):
        extra.extend(tokenize(" ".join(group)))

    return list(dict.fromkeys([*tokens, *extra]))


def _matching_groups(folded_query: str, tokens: list[str]) -> list[tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    # Primero terminos multipalabra ("dana primero"), luego token a token.
    for token in tokens:
        group = expand(token)
        if len(group) > 1 and group not in seen:
            seen.add(group)
            groups.append(group)
    for phrase, group in _PHRASES:
        if phrase in folded_query and group not in seen:
            seen.add(group)
            groups.append(group)
    return groups


def _build_phrases() -> list[tuple[str, tuple[str, ...]]]:
    phrases: list[tuple[str, tuple[str, ...]]] = []
    for group in SYNONYM_GROUPS:
        for term in group:
            if " " in term:
                phrases.append((_fold(term), group))
    return phrases


_PHRASES = _build_phrases()


class RulesIndex:
    """BM25 en memoria. Se construye una vez y se consulta N veces."""

    def __init__(self, chunks: list[RuleChunk]) -> None:
        self.chunks = chunks
        self._docs: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._df: Counter[str] = Counter()

        for chunk in chunks:
            tokens = tokenize(chunk.text) + tokenize(chunk.rule_number or "")
            if chunk.section:
                tokens += tokenize(chunk.section) * SECTION_TITLE_WEIGHT
            counts = Counter(tokens)
            self._docs.append(counts)
            self._lengths.append(len(tokens))
            self._df.update(counts.keys())

        self._n = len(chunks)
        self._avg_len = (sum(self._lengths) / self._n) if self._n else 0.0

    def __len__(self) -> int:
        return self._n

    def search(self, query: str, top_k: int = 6) -> list[RuleHit]:
        if self._n == 0:
            return []

        tokens = expand_query(query)
        if not tokens:
            return []
        referenced = set(RULE_REF_RE.findall(_fold(query)))

        scored: list[tuple[float, int]] = []
        for doc_id in range(self._n):
            score = self._score_doc(doc_id, tokens)
            if score <= 0:
                continue
            rule_number = self.chunks[doc_id].rule_number or ""
            if TOP_LEVEL_RULE_RE.match(rule_number):
                score *= TOP_LEVEL_RULE_PRIOR
            if rule_number in referenced:
                score += RULE_NUMBER_BOOST
            scored.append((score, doc_id))

        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            RuleHit(chunk=self.chunks[doc_id], score=round(score, 4))
            for score, doc_id in scored[:top_k]
        ]

    def _score_doc(self, doc_id: int, tokens: list[str]) -> float:
        counts = self._docs[doc_id]
        length = self._lengths[doc_id] or 1
        score = 0.0
        for token in tokens:
            tf = counts.get(token, 0)
            if tf == 0:
                continue
            df = self._df[token]
            idf = math.log(1 + (self._n - df + 0.5) / (df + 0.5))
            denom = tf + K1 * (1 - B + B * length / (self._avg_len or 1))
            score += idf * (tf * (K1 + 1)) / denom
        return score

    # -- Persistencia -----------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for chunk in self.chunks:
                handle.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> RulesIndex:
        if not path.exists():
            raise FileNotFoundError(
                f"No hay indice de reglas en {path}. "
                "Ejecuta: python -m mtg_assistant.rag.ingest <reglamento.pdf>"
            )
        chunks = [
            RuleChunk.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(chunks)
