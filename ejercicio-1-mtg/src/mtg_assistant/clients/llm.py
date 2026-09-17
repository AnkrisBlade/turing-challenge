"""Construccion del cliente LLM y capacidades por modelo.

Dos proveedores, mismo `messages.create`:

* **bedrock** (por defecto) -- Claude a traves de Amazon Bedrock con el perfil
  de inferencia `eu.`, que mantiene la inferencia dentro de la UE. Las
  credenciales salen de la cadena estandar de AWS (`AWS_REGION`,
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`), nunca del codigo.
* **anthropic** -- API de primera parte, con `ANTHROPIC_API_KEY`.

El cambio de proveedor no es solo un `base_url`: en Bedrock **el encargado del
tratamiento es AWS**, no Anthropic. Es una decision legal ademas de tecnica.

Lo que si cambia con el proveedor es la **forma de la peticion**, y no por el
proveedor sino por el modelo: Haiku 4.5 no acepta `thinking` adaptativo ni
`output_config.effort` (devuelve 400), mientras que Sonnet 5 y la familia Opus
4.6+ si. Por eso las capacidades se derivan del id del modelo y no del
proveedor: apuntar `MTG_MODEL` a otro modelo ajusta la peticion solo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mtg_assistant.config import Settings

# Familias que admiten `thinking` adaptativo y `output_config.effort`: de la
# 4.6 en adelante. Es una LISTA BLANCA a proposito: un id desconocido se trata
# como antiguo y se queda sin campos opcionales, que como mucho desaprovecha
# razonamiento. Al reves (lista negra) un id no reconocido -- `claude-opus-4-5`,
# `claude-3-5-sonnet-20241022` -- se mandaria con campos que el modelo rechaza
# con un 400, que es justo el fallo que este modulo existe para evitar.
#
# El id de Bedrock es el datado y con prefijo de perfil
# ("eu.anthropic.claude-haiku-4-5-20251001-v1:0"), asi que se busca el nombre
# del modelo como subcadena en lugar de comparar el id completo. El separador
# admite punto y guion porque ambas grafias circulan ("sonnet-4-6", "sonnet4.6").
_MODERN_MODEL_RE = re.compile(
    r"(?:opus|sonnet)[-.]?4[-.](?:6|7|8)"  # 4.6, 4.7, 4.8
    r"|(?:opus|sonnet|fable|mythos)[-.]?5"  # familia 5
)


@dataclass(frozen=True)
class ModelCapabilities:
    """Que campos opcionales admite este modelo en `messages.create`."""

    supports_adaptive_thinking: bool
    supports_effort: bool

    def request_extras(self, effort: str) -> dict[str, Any]:
        """Campos a anadir a la peticion; vacio si el modelo no los admite."""
        extras: dict[str, Any] = {}
        if self.supports_adaptive_thinking:
            extras["thinking"] = {"type": "adaptive"}
        if self.supports_effort:
            extras["output_config"] = {"effort": effort}
        return extras


def capabilities_for(model_id: str) -> ModelCapabilities:
    modern = bool(_MODERN_MODEL_RE.search(model_id.lower()))
    return ModelCapabilities(supports_adaptive_thinking=modern, supports_effort=modern)


def build_llm_client(settings: Settings) -> Any:
    """Cliente del proveedor configurado. Las credenciales vienen del entorno."""
    if settings.llm_provider == "bedrock":
        try:
            from anthropic import AnthropicBedrock
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "Falta el extra de Bedrock. Instala con: pip install -e '.[bedrock]'"
            ) from exc
        return AnthropicBedrock(aws_region=settings.aws_region)

    if settings.llm_provider == "anthropic":
        import anthropic

        return anthropic.Anthropic()

    raise ValueError(
        f"LLM_PROVIDER='{settings.llm_provider}' no reconocido. Usa 'bedrock' o 'anthropic'."
    )
