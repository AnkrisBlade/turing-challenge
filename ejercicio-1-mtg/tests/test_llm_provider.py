"""Seleccion de proveedor y forma de la peticion segun el modelo.

El fallo que estos tests evitan es silencioso hasta produccion: mandar
`thinking` u `output_config` a Haiku 4.5 devuelve un 400, y quitarselos a
Sonnet 5 desperdicia el razonamiento sin que nadie se entere.
"""

from __future__ import annotations

import os

import pytest

from mtg_assistant.clients.llm import build_llm_client, capabilities_for
from mtg_assistant.config import Settings, get_settings

# Los defaults ya no son constantes de codigo: salen de config/defaults.toml.
# Leerlos de `Settings` en vez de repetirlos aqui mantiene los tests validos
# si alguien cambia el fichero.
_DEFAULTS = Settings()
BEDROCK_HAIKU = _DEFAULTS.bedrock_model
ANTHROPIC_DEFAULT = _DEFAULTS.anthropic_model
BEDROCK_SONNET = "eu.anthropic.claude-sonnet-5-v1:0"


@pytest.mark.parametrize(
    "model",
    [
        BEDROCK_HAIKU,
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        # La deteccion es una lista blanca: estos ids no estan en ella y por eso
        # se quedan sin campos opcionales, en vez de recibir un 400.
        "claude-opus-4-5",
        "claude-opus-4-1",
        "claude-sonnet-4-0",
        "claude-3-5-sonnet-20241022",
        "anthropic.claude-3-haiku-20240307-v1:0",
        "un-modelo-que-no-existe",
    ],
)
def test_los_modelos_previos_a_4_6_no_admiten_thinking_ni_effort(model: str) -> None:
    caps = capabilities_for(model)
    assert not caps.supports_adaptive_thinking
    assert not caps.supports_effort
    assert caps.request_extras("medium") == {}


@pytest.mark.parametrize(
    "model",
    [
        BEDROCK_SONNET,
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-opus-4-8",
        "claude-fable-5-1",
        "eu.anthropic.claude-opus-4-6-20260101-v1:0",
    ],
)
def test_los_modelos_modernos_reciben_thinking_y_effort(model: str) -> None:
    extras = capabilities_for(model).request_extras("high")
    assert extras == {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}


def test_el_id_datado_de_bedrock_se_reconoce_igual_que_el_corto() -> None:
    """El id de Bedrock lleva perfil y fecha; la deteccion va por subcadena."""
    assert capabilities_for(BEDROCK_HAIKU) == capabilities_for("claude-haiku-4-5")


def test_el_agente_no_manda_campos_que_el_modelo_rechaza(make_agent) -> None:
    from conftest import FakeResponse, text_block

    agent = make_agent([FakeResponse([text_block("ok")], "end_turn")], model=BEDROCK_HAIKU)
    agent.chat("hola")
    call = agent.llm.messages.calls[0]
    assert "thinking" not in call
    assert "output_config" not in call


def test_el_agente_manda_effort_configurable_si_el_modelo_lo_admite(make_agent) -> None:
    from conftest import FakeResponse, text_block

    agent = make_agent(
        [FakeResponse([text_block("ok")], "end_turn")], model="claude-opus-5", effort="high"
    )
    agent.chat("hola")
    call = agent.llm.messages.calls[0]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "high"}


def test_el_prefijo_cacheable_se_mantiene_en_ambos_proveedores(make_agent) -> None:
    """El breakpoint explicito es obligatorio: Bedrock clasico rechaza el de nivel superior."""
    from conftest import FakeResponse, text_block

    for model in (BEDROCK_HAIKU, "claude-opus-5"):
        agent = make_agent([FakeResponse([text_block("ok")], "end_turn")], model=model)
        agent.chat("hola")
        system = agent.llm.messages.calls[0]["system"]
        assert system[0]["cache_control"] == {"type": "ephemeral"}


# --- resolucion desde el entorno -----------------------------------------
def test_por_defecto_el_proveedor_es_bedrock_con_el_modelo_eu(monkeypatch) -> None:
    for var in ("LLM_PROVIDER", "MTG_MODEL", "AWS_REGION"):
        monkeypatch.delenv(var, raising=False)
    settings = get_settings()
    assert settings.llm_provider == "bedrock"
    assert settings.model == BEDROCK_HAIKU
    assert settings.aws_region == "eu-west-1"


def test_cambiar_de_proveedor_cambia_el_modelo_por_defecto(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("MTG_MODEL", raising=False)
    assert get_settings().model == ANTHROPIC_DEFAULT


def test_un_modelo_explicito_gana_al_defecto_del_proveedor(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("MTG_MODEL", BEDROCK_SONNET)
    assert get_settings().model == BEDROCK_SONNET


def test_el_proveedor_se_normaliza(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "  Bedrock  ")
    assert get_settings().llm_provider == "bedrock"


def test_un_proveedor_desconocido_falla_con_un_mensaje_util() -> None:
    with pytest.raises(ValueError, match="no reconocido"):
        build_llm_client(Settings(llm_provider="openai"))


def test_build_llm_client_construye_el_cliente_de_bedrock(monkeypatch) -> None:
    """No se llama a AWS: solo se comprueba que se elige la clase y la region."""
    import mtg_assistant.clients.llm as llm_module

    capturado: dict[str, str] = {}

    class FakeBedrock:
        def __init__(self, aws_region: str) -> None:
            capturado["region"] = aws_region

    monkeypatch.setattr("anthropic.AnthropicBedrock", FakeBedrock, raising=False)
    cliente = llm_module.build_llm_client(
        Settings(llm_provider="bedrock", aws_region="eu-central-1")
    )
    assert isinstance(cliente, FakeBedrock)
    assert capturado["region"] == "eu-central-1"


# --- variables definidas pero vacias --------------------------------------
@pytest.mark.parametrize(
    ("var", "atributo", "esperado"),
    [
        ("LLM_PROVIDER", "llm_provider", "bedrock"),
        ("AWS_REGION", "aws_region", "eu-west-1"),
        ("MTG_MODEL", "model", BEDROCK_HAIKU),
        ("MTG_EFFORT", "effort", "medium"),
        ("MTG_API_URL", "api_url", "http://127.0.0.1:8000"),
    ],
)
def test_una_variable_vacia_cae_al_defecto(monkeypatch, var, atributo, esperado) -> None:
    """`LLM_PROVIDER=` en el `.env` no es "sin proveedor", es una linea a medio borrar."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv(var, "")
    assert getattr(get_settings(), atributo) == esperado


def test_los_marcadores_del_env_de_ejemplo_no_se_exportan(monkeypatch, tmp_path) -> None:
    """Copiar `.env.example` tal cual no debe secuestrar la cadena de AWS."""
    import mtg_assistant.config as config

    env = tmp_path / ".env"
    env.write_text("AWS_ACCESS_KEY_ID=...\nAWS_REGION=eu-central-1\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)

    config._export_dotenv()

    assert "AWS_ACCESS_KEY_ID" not in os.environ
    assert os.environ["AWS_REGION"] == "eu-central-1"
