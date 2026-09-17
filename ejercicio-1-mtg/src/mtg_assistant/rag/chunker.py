"""Troceado del reglamento en fragmentos citables.

El reglamento de Magic esta numerado ("509.1a. El jugador atacante..."), y esa
numeracion es justo la unidad de cita que queremos mostrar al usuario. Por eso
el chunker tiene dos modos:

* `numbered`: una regla numerada = un chunk. Cita exacta ("regla 509.1a").
* `paragraph`: fallback por ventanas de parrafos cuando el documento no esta
  numerado (guias, FAQs). Cita por pagina.

El modo se elige solo, midiendo cuantas lineas empiezan por un numero de regla.
"""

from __future__ import annotations

import re

from mtg_assistant.models import RuleChunk

# "509.1a." / "100.2." / "702.7b." al principio de linea.
#
# El separador es "punto + lo que sea" o "espacio": los extractores de PDF se
# comen el espacio tras el punto ("106.1.Manais the primary resource") y exigir
# \s+ hacia que esas reglas -- justo las definitorias -- se perdieran dentro
# del chunk anterior.
RULE_NUMBER_RE = re.compile(r"^\s*(\d{3}\.\d+[a-z]?)(?:\.\s*|\s+)(?=\S)")
# "5. Fases y pasos" / "106. Mana" -- encabezado de seccion.
# El titulo no puede acabar en "." ni ")": esas lineas son continuaciones de un
# parrafo partido, no encabezados ("704. See also rule 903.10.)").
SECTION_RE = re.compile(
    r"^\s*(\d{1,3})\.\s+([A-ZÁÉÍÓÚÑ][^\n]{2,79}[^\s.)])\s*$"
)
# Marcador de pagina que inserta el extractor de PDF.
PAGE_MARKER_RE = re.compile(r"^\s*<<<PAGE:(\d+)>>>\s*$")

MIN_CHUNK_CHARS = 40
NUMBERED_MODE_THRESHOLD = 0.10  # 10% de lineas numeradas basta


def detect_mode(text: str) -> str:
    """Devuelve 'numbered' o 'paragraph' segun la densidad de reglas numeradas."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "paragraph"
    numbered = sum(1 for ln in lines if RULE_NUMBER_RE.match(ln))
    return "numbered" if numbered / len(lines) >= NUMBERED_MODE_THRESHOLD else "paragraph"


def chunk_document(text: str, *, mode: str | None = None) -> list[RuleChunk]:
    """Trocea el texto completo del reglamento."""
    mode = mode or detect_mode(text)
    if mode == "numbered":
        return _chunk_numbered(text)
    return _chunk_paragraphs(text)


def _chunk_numbered(text: str) -> list[RuleChunk]:
    chunks: list[RuleChunk] = []
    current: dict | None = None
    section: str | None = None
    page: int | None = None

    def flush() -> None:
        if current is None:
            return
        body = " ".join(current["lines"]).strip()
        if len(body) < MIN_CHUNK_CHARS:
            return
        chunks.append(
            RuleChunk(
                chunk_id=f"rule-{current['number']}",
                rule_number=current["number"],
                section=current["section"],
                page=current["page"],
                text=body,
            )
        )

    for line in text.splitlines():
        page_match = PAGE_MARKER_RE.match(line)
        if page_match:
            page = int(page_match.group(1))
            continue

        section_match = SECTION_RE.match(line)
        if section_match:
            flush()
            current = None
            section = f"{section_match.group(1)}. {section_match.group(2).strip()}"
            continue

        rule_match = RULE_NUMBER_RE.match(line)
        if rule_match:
            flush()
            number = rule_match.group(1)
            rest = line[rule_match.end():].strip()
            current = {"number": number, "section": section, "page": page, "lines": [rest]}
            continue

        if current is not None and line.strip():
            current["lines"].append(line.strip())

    flush()
    return chunks


def _chunk_paragraphs(text: str, *, window: int = 3, overlap: int = 1) -> list[RuleChunk]:
    """Ventana deslizante de parrafos, con solape para no cortar una idea."""
    paragraphs: list[tuple[int | None, str]] = []
    page: int | None = None
    buffer: list[str] = []

    def flush_paragraph() -> None:
        body = " ".join(buffer).strip()
        if body:
            paragraphs.append((page, body))
        buffer.clear()

    for line in text.splitlines():
        page_match = PAGE_MARKER_RE.match(line)
        if page_match:
            flush_paragraph()
            page = int(page_match.group(1))
            continue
        if line.strip():
            buffer.append(line.strip())
        else:
            flush_paragraph()
    flush_paragraph()

    step = max(1, window - overlap)
    chunks: list[RuleChunk] = []
    for start in range(0, len(paragraphs), step):
        group = paragraphs[start:start + window]
        body = "\n\n".join(p for _, p in group)
        if len(body) < MIN_CHUNK_CHARS:
            continue
        chunks.append(
            RuleChunk(
                chunk_id=f"par-{start:04d}",
                rule_number=None,
                section=None,
                page=group[0][0],
                text=body,
            )
        )
        if start + window >= len(paragraphs):
            break
    return chunks
