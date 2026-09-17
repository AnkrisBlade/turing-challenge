"""Las herramientas son el contrato con el modelo: aqui se fija su comportamiento."""

from __future__ import annotations

from dataclasses import replace

from mtg_assistant.tools import ALL_TOOLS, build_registry
from mtg_assistant.tools.base import ToolContext
from mtg_assistant.tools.cards import get_card, list_recent_sets, search_cards
from mtg_assistant.tools.designer import design_custom_card
from mtg_assistant.tools.rules import search_rules


# --- contrato general -----------------------------------------------------
def test_todos_los_esquemas_son_validos_para_la_api() -> None:
    for tool in ALL_TOOLS:
        schema = tool.to_api_schema()
        assert schema["name"] and schema["description"]
        assert schema["input_schema"]["type"] == "object"
        assert schema["input_schema"]["additionalProperties"] is False


def test_el_registro_no_tiene_nombres_duplicados() -> None:
    assert len(build_registry()) == len(ALL_TOOLS)


# --- reglas ---------------------------------------------------------------
def test_search_rules_devuelve_citas_con_numero(tool_context: ToolContext) -> None:
    result = search_rules(tool_context, query="fases de un turno")
    assert result.ok
    assert any(c.label == "regla 500.1" for c in result.citations)
    assert "500.1" in result.content


def test_search_rules_vacia_es_error(tool_context: ToolContext) -> None:
    assert not search_rules(tool_context, query="   ").ok


def test_sin_resultados_el_modelo_recibe_instruccion_de_no_inventar(
    tool_context: ToolContext,
) -> None:
    result = search_rules(tool_context, query="hipoteca variable euribor")
    assert result.ok  # no es un fallo tecnico
    assert "improvisar" in result.content
    assert result.citations == []


def test_top_k_se_acota_al_maximo(tool_context: ToolContext) -> None:
    result = search_rules(tool_context, query="dano", top_k=999)
    assert len(result.citations) <= 10


def test_sin_top_k_explicito_manda_la_configuracion(tool_context: ToolContext) -> None:
    """`MTG_RULES_TOP_K` decide cuando el modelo no pide un numero concreto."""
    acotado = replace(
        tool_context, settings=tool_context.settings.model_copy(update={"rules_top_k": 1})
    )
    assert len(search_rules(acotado, query="dano").citations) == 1


# --- cartas ---------------------------------------------------------------
def test_search_cards_traduce_guerrero_a_warrior(tool_context: ToolContext) -> None:
    result = search_cards(
        tool_context, colors=["blanco"], types=["Creature"], subtypes=["Warrior"], cmc_max=1
    )
    assert result.ok
    assert "Mardu Woe-Reaper" in result.content
    assert result.payload is not None and len(result.payload["cards"]) == 1


def test_search_cards_rechaza_un_color_inventado(tool_context: ToolContext) -> None:
    result = search_cards(tool_context, colors=["turquesa"])
    assert not result.ok
    assert "turquesa" in result.content


def test_search_cards_sin_resultados_sugiere_relajar_filtros(
    tool_context: ToolContext,
) -> None:
    result = search_cards(tool_context, subtypes=["Dinosaur"])
    assert result.ok and "relajar" in result.content


def test_get_card_devuelve_ficha_y_cita(tool_context: ToolContext) -> None:
    result = get_card(tool_context, name="Wojek Halberdiers")
    assert result.ok
    assert "First strike" in result.content
    assert result.citations[0].label == "Wojek Halberdiers"


def test_get_card_inexistente_no_es_error_tecnico(tool_context: ToolContext) -> None:
    result = get_card(tool_context, name="Rapaz del campo de batalla")
    assert result.ok
    assert "No existe" in result.content


def test_get_card_sin_nombre_es_error(tool_context: ToolContext) -> None:
    assert not get_card(tool_context, name="").ok


def test_list_recent_sets(tool_context: ToolContext) -> None:
    result = list_recent_sets(tool_context, limit=2)
    assert result.ok
    assert "Outlaws of Thunder Junction" in result.content


# --- carta custom (bonus) -------------------------------------------------
def _han_solo(**overrides) -> dict:
    base = {
        "name": "Han Solo, Contrabandista",
        "mana_cost": "{1}{R}{W}",
        "type_line": "Legendary Creature - Human Rogue",
        "rules_text": "Dana primero. Cuando Han Solo entra al campo de batalla, roba una carta.",
        "power": "3",
        "toughness": "2",
        "colors": ["R", "W"],
    }
    base.update(overrides)
    return base


def test_carta_custom_valida_pasa_y_cita_su_palabra_clave(tool_context: ToolContext) -> None:
    result = design_custom_card(tool_context, **_han_solo())
    assert result.ok
    assert result.payload is not None
    assert result.payload["custom_card"]["colors"] == ["R", "W"]
    assert any(c.detail == "dana primero" for c in result.citations)


def test_coste_de_mana_mal_escrito_se_rechaza(tool_context: ToolContext) -> None:
    result = design_custom_card(tool_context, **_han_solo(mana_cost="1RW"))
    assert not result.ok
    assert "notacion oficial" in result.content


def test_colores_incoherentes_con_el_coste_se_rechazan(tool_context: ToolContext) -> None:
    result = design_custom_card(tool_context, **_han_solo(colors=["U"]))
    assert not result.ok
    assert "no coinciden" in result.content


def test_criatura_sin_fuerza_resistencia_se_rechaza(tool_context: ToolContext) -> None:
    payload = _han_solo()
    payload.pop("power")
    payload.pop("toughness")
    result = design_custom_card(tool_context, **payload)
    assert not result.ok
    assert "fuerza y resistencia" in result.content


def test_un_instantaneo_con_fuerza_resistencia_se_rechaza(tool_context: ToolContext) -> None:
    result = design_custom_card(
        tool_context, **_han_solo(type_line="Instant", rules_text="Inflige 3 de dano.")
    )
    assert not result.ok
    assert "Solo las criaturas" in result.content


def test_coste_hibrido_y_generico_se_aceptan(tool_context: ToolContext) -> None:
    result = design_custom_card(
        tool_context,
        **_han_solo(mana_cost="{2}{R/W}{W}", colors=["R", "W"]),
    )
    assert result.ok


def test_faltan_campos_obligatorios_no_revienta(tool_context: ToolContext) -> None:
    result = design_custom_card(tool_context, name="Solo un nombre")
    assert not result.ok
    assert "invalida" in result.content
