"""Configuracion central.

Los valores por defecto NO viven aqui: viven en `config/defaults.toml`, que se
versiona y se puede leer sin abrir codigo Python. Este modulo solo declara
*que* campos existen, de que tipo son, y en que orden ganan las fuentes:

    variable de entorno  >  config/defaults.toml  >  default del campo

El default declarado en cada campo es una red de seguridad, no la fuente de
verdad: solo actua si alguien borra la clave del TOML. Los secretos no estan
en ninguno de los dos, solo en el entorno.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULTS_FILE = PROJECT_ROOT / "config" / "defaults.toml"

# Valores de `.env.example` que no son valores: vacio o puntos suspensivos.
_PLACEHOLDERS = frozenset({"", "...", "…"})


def _export_dotenv() -> None:
    """Vuelca el `.env` en `os.environ`, sin pisar lo ya definido.

    No es la carga de `Settings`: existe porque `boto3` busca las credenciales
    en `os.environ`, no en nuestro modelo, y ni `uvicorn` ni `streamlit` leen un
    `.env` por su cuenta. Lo ya exportado manda, para que un `.env` colado en una
    imagen no pise las credenciales del orquestador; y los marcadores del
    `.env.example` (`AWS_ACCESS_KEY_ID=...`) se ignoran, porque exportar ese
    `...` literal secuestraria la cadena de credenciales de AWS.
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value not in _PLACEHOLDERS and key not in os.environ:
            os.environ[key] = value


_export_dotenv()


class _EnvSinBlancos(EnvSettingsSource):
    """Trata una variable definida pero vacia como no definida.

    `LLM_PROVIDER=` es una linea a medio borrar, no "sin proveedor". No se puede
    resolver con un validador: lo que hace falta es que el valor *caiga a la
    fuente siguiente*, y eso solo se decide aqui.
    """

    def __call__(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in super().__call__().items()
            if not (isinstance(value, str) and not value.strip())
        }


class Settings(BaseSettings):
    """Ajustes de ejecucion resueltos una sola vez por proceso."""

    model_config = SettingsConfigDict(
        toml_file=DEFAULTS_FILE,
        extra="ignore",
        frozen=True,
        # Con esto las claves del TOML casan por nombre de campo y el entorno
        # por el alias en MAYUSCULAS. Sin esto el campo SOLO responde al alias,
        # el TOML se ignora en silencio y todo cae al default declarado.
        populate_by_name=True,
    )

    # --- LLM ---------------------------------------------------------------
    llm_provider: str = Field("bedrock", validation_alias="LLM_PROVIDER")
    aws_region: str = Field("eu-west-1", validation_alias="AWS_REGION")
    max_tokens: int = Field(8000, validation_alias="MTG_MAX_TOKENS")
    effort: str = Field("medium", validation_alias="MTG_EFFORT")
    max_tool_turns: int = Field(8, validation_alias="MTG_MAX_TOOL_TURNS")

    # Un modelo por proveedor: los ids no son intercambiables entre plataformas.
    # `model` lo elige el proveedor salvo que se fije MTG_MODEL a mano.
    bedrock_model: str = Field(
        "eu.anthropic.claude-haiku-4-5-20251001-v1:0", validation_alias="MTG_BEDROCK_MODEL"
    )
    anthropic_model: str = Field("claude-haiku-4-5", validation_alias="MTG_ANTHROPIC_MODEL")
    model: str = Field("", validation_alias="MTG_MODEL")

    # --- RAG de reglas -----------------------------------------------------
    rules_index_path: Path = Field(
        Path("data/index/rules.jsonl"), validation_alias="MTG_RULES_INDEX"
    )
    rules_top_k: int = Field(6, validation_alias="MTG_RULES_TOP_K")

    # --- UI ----------------------------------------------------------------
    api_url: str = Field("http://127.0.0.1:8000", validation_alias="MTG_API_URL")

    # --- API de cartas -----------------------------------------------------
    mtg_api_base_url: str = Field(
        "https://api.magicthegathering.io/v1", validation_alias="MTG_API_BASE_URL"
    )
    mtg_api_timeout: float = Field(15.0, validation_alias="MTG_API_TIMEOUT")
    mtg_api_page_size: int = Field(100, validation_alias="MTG_API_PAGE_SIZE")
    mtg_api_max_pages: int = Field(3, validation_alias="MTG_API_MAX_PAGES")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """El entorno gana al TOML, y el TOML al default del campo.

        El `.env` no es una fuente aqui: `_export_dotenv()` ya lo volco en
        `os.environ`, que es la misma via que ven las credenciales de AWS.
        """
        return (init_settings, _EnvSinBlancos(settings_cls), TomlConfigSettingsSource(settings_cls))

    @model_validator(mode="after")
    def _resuelve_derivados(self) -> Settings:
        """Lo que depende de otros campos, una vez estan todos leidos.

        La ruta se ancla a la raiz del proyecto y no al cwd porque, resuelta
        contra el directorio del proceso, arrancar `uvicorn` desde otro sitio
        daba un `/health` degradado sin explicar por que.
        """
        object.__setattr__(self, "llm_provider", self.llm_provider.strip().lower())

        if not self.model.strip():
            por_proveedor = (
                self.bedrock_model if self.llm_provider == "bedrock" else self.anthropic_model
            )
            object.__setattr__(self, "model", por_proveedor)

        ruta = self.rules_index_path.expanduser()
        if not ruta.is_absolute():
            ruta = PROJECT_ROOT / ruta
        object.__setattr__(self, "rules_index_path", ruta)
        return self


def get_settings() -> Settings:
    """Se construye en cada llamada: los tests pueden monkeypatchear el entorno."""
    return Settings()
