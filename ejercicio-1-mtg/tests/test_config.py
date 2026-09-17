"""El fichero de defaults manda de verdad, y sus claves llegan a `Settings`.

Estos tests existen por un fallo concreto: con `extra="ignore"`, un TOML que no
case con los campos se ignora **en silencio** y todo cae al default declarado en
el codigo. Todo parece funcionar --- los valores son plausibles --- pero el
fichero de configuracion ha dejado de tener efecto. Eso paso al montar esto, y
solo se vio cambiando un valor a proposito para ver si viajaba.
"""

from __future__ import annotations

import tomllib

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from mtg_assistant.config import DEFAULTS_FILE, PROJECT_ROOT, Settings

# Rutas que el modelo ancla a la raiz del proyecto, asi que el valor del TOML
# no se compara tal cual.
_CAMPOS_RUTA = {"rules_index_path"}


def _defaults_del_toml() -> dict[str, object]:
    return tomllib.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))


def _variables_de_entorno() -> list[str]:
    """El nombre en MAYUSCULAS de cada campo, que es lo que pisa al TOML."""
    return [
        campo.validation_alias
        for campo in Settings.model_fields.values()
        if isinstance(campo.validation_alias, str)
    ]


@pytest.fixture
def sin_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aisla del `.env` del desarrollador: aqui se mide el TOML, no la maquina."""
    for var in _variables_de_entorno():
        monkeypatch.delenv(var, raising=False)


def test_el_fichero_de_defaults_existe() -> None:
    assert DEFAULTS_FILE.exists(), f"no hay defaults en {DEFAULTS_FILE}"


def test_ninguna_clave_del_toml_se_ignora_en_silencio() -> None:
    """Una clave mal escrita no da error: `extra="ignore"` la tira sin avisar."""
    desconocidas = set(_defaults_del_toml()) - set(Settings.model_fields)
    assert not desconocidas, (
        f"claves del TOML que no son campos de Settings y se descartarian "
        f"sin avisar: {sorted(desconocidas)}"
    )


def test_cada_valor_del_toml_llega_a_settings(sin_entorno: None) -> None:
    """Sin esto, que el TOML no se leyera pasaria desapercibido."""
    settings = Settings()
    for clave, esperado in _defaults_del_toml().items():
        actual = getattr(settings, clave)
        if clave in _CAMPOS_RUTA:
            esperado = PROJECT_ROOT / str(esperado)
        assert actual == esperado, f"{clave}: el TOML dice {esperado!r} y Settings {actual!r}"


def test_el_toml_gana_al_default_declarado_en_el_campo(tmp_path, sin_entorno: None) -> None:
    """El default del campo es una red de seguridad, no la fuente de verdad.

    Se usa un TOML de prueba con un valor que no aparece en ningun sitio mas:
    comparar contra `config/defaults.toml` no demostraria nada mientras sus
    valores coincidan con los defaults declarados, que es justo lo que hizo
    pasar desapercibido que el fichero no se estaba leyendo.
    """
    fichero = tmp_path / "defaults.toml"
    fichero.write_text("max_tokens = 4242\n", encoding="utf-8")

    class _SettingsDePrueba(Settings):
        model_config = SettingsConfigDict(**{**Settings.model_config, "toml_file": fichero})

    assert Settings.model_fields["max_tokens"].default != 4242
    assert _SettingsDePrueba().max_tokens == 4242


def test_el_entorno_gana_al_toml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MTG_MAX_TOKENS", "4321")
    assert Settings().max_tokens == 4321


def test_una_ruta_relativa_se_ancla_a_la_raiz_del_proyecto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contra el cwd, arrancar uvicorn desde otro sitio daba /health degradado."""
    monkeypatch.setenv("MTG_RULES_INDEX", "data/otro/indice.jsonl")
    ruta = Settings().rules_index_path
    assert ruta.is_absolute()
    assert ruta == PROJECT_ROOT / "data" / "otro" / "indice.jsonl"


def test_una_ruta_absoluta_se_respeta(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    destino = tmp_path / "indice.jsonl"
    monkeypatch.setenv("MTG_RULES_INDEX", str(destino))
    assert Settings().rules_index_path == destino


def test_los_ajustes_son_inmutables() -> None:
    """Se resuelven una vez por proceso; nadie los cambia a mitad de turno."""
    with pytest.raises(ValidationError):
        Settings().max_tokens = 1
