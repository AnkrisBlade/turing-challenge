"""CLI de ingesta: reglamento (PDF o TXT) -> indice de fragmentos citables.

    python -m mtg_assistant.rag.ingest data/raw/reglamento.pdf

Escribe `data/index/rules.jsonl` (una linea por chunk). El indice es un
artefacto reproducible: se regenera desde el PDF y no se versiona.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from mtg_assistant.config import get_settings
from mtg_assistant.rag.chunker import chunk_document
from mtg_assistant.rag.index import RulesIndex

PAGE_MARKER = "<<<PAGE:{page}>>>"

# Los extractores de PDF pierden los espacios que rodean a los tramos en
# cursiva, y el reglamento pone en cursiva cada termino que define. El
# resultado son pegados como "106.1.Manais the primary resource" o
# "bymana symbols(see rule 107.4)", que rompen a la vez el troceado y la
# tokenizacion. Estas tres reglas cubren los casos recuperables sin
# diccionario; los pegados minuscula-minuscula ("acolor") no lo son.
GLUE_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d)\.([A-Za-z])"), r"\1. \2"),   # 106.1.Mana -> 106.1. Mana
    (re.compile(r"([a-z])([A-Z])"), r"\1 \2"),       # TheMagicGolden -> The Magic Golden
    (re.compile(r"([a-zA-Z])\("), r"\1 ("),          # symbols(see -> symbols (see
)


def normalize_extracted_text(text: str) -> str:
    """Repara los pegados tipicos de la extraccion de PDF."""
    for pattern, replacement in GLUE_FIXES:
        text = pattern.sub(replacement, text)
    return text


def extract_text(path: Path) -> str:
    """Devuelve el texto plano con marcadores de pagina intercalados."""
    if path.suffix.lower() == ".pdf":
        return _extract_pdf(path)
    return path.read_text(encoding="utf-8")


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise SystemExit(
            "Falta 'pypdf' para leer PDFs. Instala con: pip install -e '.[ingest]'"
        ) from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        parts.append(PAGE_MARKER.format(page=number))
        parts.append(normalize_extracted_text(page.extract_text() or ""))
    return "\n".join(parts)


def build_index(source: Path, destination: Path, *, mode: str | None = None) -> RulesIndex:
    text = extract_text(source)
    chunks = chunk_document(text, mode=mode)
    if not chunks:
        raise SystemExit(f"No se extrajo ningun fragmento de {source}.")
    index = RulesIndex(chunks)
    index.save(destination)
    return index


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Indexa el reglamento de Magic.")
    parser.add_argument("source", type=Path, help="PDF o TXT del reglamento")
    parser.add_argument(
        "-o", "--output", type=Path, default=settings.rules_index_path,
        help="Ruta del indice de salida (.jsonl)",
    )
    parser.add_argument(
        "--mode", choices=["numbered", "paragraph"], default=None,
        help="Fuerza el modo de troceado (por defecto se detecta solo)",
    )
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"No existe el fichero {args.source}", file=sys.stderr)
        return 1

    index = build_index(args.source, args.output, mode=args.mode)
    numbered = sum(1 for c in index.chunks if c.rule_number)
    print(f"{len(index)} fragmentos ({numbered} con numero de regla) -> {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
