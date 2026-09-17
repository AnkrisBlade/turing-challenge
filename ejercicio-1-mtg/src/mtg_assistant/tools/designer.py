"""Bonus: creacion de cartas custom con validacion contra el reglamento.

El modelo propone la carta; esta herramienta la VALIDA. Sin validacion el bonus
seria solo texto generado: aqui se comprueba que el coste de mana este bien
escrito, que los colores declarados coincidan con los simbolos del coste, que
una criatura traiga fuerza/resistencia, y que cada palabra clave usada exista
de verdad en el reglamento (adjuntando la cita).
"""

from __future__ import annotations

import re
from typing import Any

from mtg_assistant.models import Citation, CustomCard
from mtg_assistant.tools.base import Tool, ToolContext, ToolResult

# {2}{W}{R}, {X}, {C}, hibridos {W/U} y Phyrexian {W/P}.
MANA_SYMBOL_RE = re.compile(r"\{(?:\d+|[XYZCSWUBRG]|[WUBRG]/[WUBRGP])\}")
COLOR_SYMBOLS = {"W", "U", "B", "R", "G"}

# Palabras clave que sabemos buscar en el reglamento, en ES y EN.
# Se parece al glosario de `rag/glossary.py` pero NO se deriva de el: alli el
# vocabulario es para expandir consultas (incluye 'criatura', 'dano', 'mano'...)
# y aqui `_keywords_in` hace busqueda por subcadena, asi que esos terminos
# generales dispararian una consulta de respaldo por casi cualquier carta.
KNOWN_KEYWORDS: tuple[str, ...] = (
    "dana primero", "first strike", "dana doble", "double strike",
    "arrollar", "trample", "vigilancia", "vigilance", "volar", "flying",
    "prisa", "haste", "defensor", "defender", "toque mortal", "deathtouch",
    "vinculo vital", "lifelink", "amenaza", "menace", "alcance", "reach",
)


def _colors_from_mana_cost(mana_cost: str) -> set[str]:
    colors: set[str] = set()
    for symbol in MANA_SYMBOL_RE.findall(mana_cost):
        for char in symbol.strip("{}").split("/"):
            if char in COLOR_SYMBOLS:
                colors.add(char)
    return colors


def _is_valid_mana_cost(mana_cost: str) -> bool:
    if not mana_cost:
        return False
    return "".join(MANA_SYMBOL_RE.findall(mana_cost)) == mana_cost.replace(" ", "")


def _keywords_in(text: str) -> list[str]:
    lowered = text.lower()
    return [kw for kw in KNOWN_KEYWORDS if kw in lowered]


def design_custom_card(context: ToolContext, **kwargs: Any) -> ToolResult:
    try:
        card = CustomCard(**kwargs)
    except Exception as exc:  # pydantic ValidationError u otros
        return ToolResult.error(f"Propuesta de carta invalida: {exc}")

    problems: list[str] = []

    if not _is_valid_mana_cost(card.mana_cost):
        problems.append(
            f"El coste '{card.mana_cost}' no usa la notacion oficial. "
            "Ejemplo correcto: {1}{R}{W}."
        )
        cost_colors: set[str] = set()
    else:
        cost_colors = _colors_from_mana_cost(card.mana_cost)

    declared = {c.upper() for c in card.colors}
    if declared and cost_colors and declared != cost_colors:
        problems.append(
            f"Los colores declarados {sorted(declared)} no coinciden con los simbolos "
            f"del coste {sorted(cost_colors)}."
        )

    is_creature = "creature" in card.type_line.lower() or "criatura" in card.type_line.lower()
    has_pt = card.power is not None and card.toughness is not None
    if is_creature and not has_pt:
        problems.append("Una criatura necesita fuerza y resistencia.")
    if not is_creature and has_pt:
        problems.append("Solo las criaturas llevan fuerza/resistencia.")

    if problems:
        return ToolResult(
            content=(
                "La carta propuesta no es valida todavia:\n- "
                + "\n- ".join(problems)
                + "\nCorrigela y vuelve a llamar a design_custom_card."
            ),
            ok=False,
            summary=f"{len(problems)} problemas de validacion",
        )

    # La carta es estructuralmente valida: respaldamos sus palabras clave.
    citations: list[Citation] = []
    keyword_notes: list[str] = []
    for keyword in _keywords_in(f"{card.rules_text} {card.type_line}"):
        hits = context.rules_index.search(keyword, top_k=1)
        if not hits:
            keyword_notes.append(f"'{keyword}': sin respaldo en el reglamento indexado.")
            continue
        chunk = hits[0].chunk
        label = f"regla {chunk.rule_number}" if chunk.rule_number else f"pag. {chunk.page}"
        keyword_notes.append(f"'{keyword}' -> {label}")
        citations.append(Citation(kind="rule", label=label, detail=keyword))

    card = card.model_copy(update={"colors": sorted(cost_colors) or card.colors})

    lines = [
        "Carta custom validada:",
        f"{card.name} {card.mana_cost}",
        card.type_line,
        card.rules_text,
    ]
    if card.power is not None:
        lines.append(f"{card.power}/{card.toughness}")
    if card.flavor_text:
        lines.append(f'"{card.flavor_text}"')
    if keyword_notes:
        lines.append("Respaldo de palabras clave: " + "; ".join(keyword_notes))

    return ToolResult(
        content="\n".join(lines),
        summary=f"carta '{card.name}' validada",
        citations=citations,
        payload={"custom_card": card.model_dump()},
    )


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Nombre de la carta."},
        "mana_cost": {
            "type": "string",
            "description": "Notacion oficial con llaves, p.ej. '{1}{R}{W}'.",
        },
        "type_line": {
            "type": "string",
            "description": "Linea de tipo completa, p.ej. 'Creature - Human Rogue'.",
        },
        "rules_text": {"type": "string", "description": "Texto de reglas de la carta."},
        "flavor_text": {"type": "string", "description": "Texto de ambientacion (opcional)."},
        "power": {"type": "string", "description": "Fuerza. Solo criaturas."},
        "toughness": {"type": "string", "description": "Resistencia. Solo criaturas."},
        "colors": {
            "type": "array",
            "items": {"type": "string", "enum": ["W", "U", "B", "R", "G"]},
            "description": "Colores de la carta; deben coincidir con el coste.",
        },
        "rarity": {
            "type": "string",
            "enum": ["common", "uncommon", "rare", "mythic"],
        },
        "design_notes": {
            "type": "string",
            "description": "Por que el coste y las estadisticas son razonables.",
        },
    },
    "required": ["name", "mana_cost", "type_line", "rules_text"],
    "additionalProperties": False,
}

TOOL = Tool(
    name="design_custom_card",
    description=(
        "Crea una carta inventada y la valida: notacion del coste de mana, coherencia "
        "entre colores y coste, fuerza/resistencia solo en criaturas, y respaldo de "
        "cada palabra clave en el reglamento. Si devuelve errores, corrige la "
        "propuesta y vuelve a llamarla."
    ),
    input_schema=SCHEMA,
    handler=design_custom_card,
)
