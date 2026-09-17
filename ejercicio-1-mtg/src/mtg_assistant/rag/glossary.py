"""Glosario ES<->EN de terminos de juego.

El reglamento puede venir en cualquiera de los dos idiomas y el usuario del
call center escribe en espanol. Expandir la consulta con los equivalentes
evita el fallo mas comun del lexico puro: preguntar por "dana primero" contra
un reglamento que dice "first strike".
"""

from __future__ import annotations

# Cada entrada es un grupo de sinonimos intercambiables.
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("dana primero", "danar primero", "first strike"),
    ("dana doble", "double strike"),
    ("arrollar", "trample"),
    ("vigilancia", "vigilance"),
    ("volar", "vuela", "flying"),
    ("defensor", "defender"),
    ("prisa", "haste"),
    ("toque mortal", "deathtouch"),
    ("vinculo vital", "lifelink"),
    ("criatura", "criaturas", "creature", "creatures"),
    ("hechizo", "hechizos", "spell", "spells"),
    ("conjuro", "sorcery"),
    ("instantaneo", "instant"),
    ("tierra", "tierras", "land", "lands"),
    ("encantamiento", "enchantment"),
    ("artefacto", "artifact"),
    ("planeswalker", "caminante de planos"),
    ("fase", "fases", "phase", "phases"),
    ("paso", "pasos", "step", "steps"),
    ("turno", "turnos", "turn", "turns"),
    ("mantenimiento", "upkeep"),
    ("robar", "robo", "draw"),
    ("principal", "main"),
    ("combate", "combat"),
    ("atacante", "attacking", "attacker"),
    ("bloqueador", "bloqueadora", "blocker", "blocking"),
    ("dano", "damage"),
    ("pila", "stack"),
    ("cementerio", "graveyard"),
    ("biblioteca", "library"),
    ("campo de batalla", "battlefield"),
    ("destruir", "destroy"),
    ("exiliar", "exile"),
    ("contrarrestar", "counter"),
    ("habilidad", "habilidades", "ability", "abilities"),
    ("disparada", "activada", "triggered", "activated"),
    ("marcador", "marcadores", "counter", "counters"),
    ("estados", "state-based", "acciones basadas en estado"),
    ("prioridad", "priority"),
    ("mazo", "deck"),
    ("mano", "hand"),
    ("vidas", "vida", "life"),
)

# term -> set de terminos equivalentes (incluye el propio).
# `setdefault`: un termino que aparece en dos grupos se queda con el primero.
# Pasa a proposito con "counter", que se lo lleva el grupo de 'contrarrestar'
# (en ingles, counter = contrarrestar un hechizo). El grupo de 'marcador' sigue
# alcanzandose por sus terminos en espanol, que es como escribe el cliente.
_LOOKUP: dict[str, tuple[str, ...]] = {}
for _group in SYNONYM_GROUPS:
    for _term in _group:
        _LOOKUP.setdefault(_term, _group)


def expand(term: str) -> tuple[str, ...]:
    """Devuelve el termino y sus equivalentes conocidos."""
    return _LOOKUP.get(term, (term,))
