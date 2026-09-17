"""UI de demo en Streamlit.

    streamlit run src/mtg_assistant/ui.py

Habla con la API por HTTP a proposito: la demo ejercita el mismo contrato que
usaria el canal real del call center, no un atajo en proceso.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

import httpx
import streamlit as st

from mtg_assistant.config import get_settings
from mtg_assistant.images import safe_card_image_url

# Importar la config carga tambien el `.env` del proyecto, que es como la UI
# acaba sabiendo en que puerto escucha la API.
_SETTINGS = get_settings()
API_URL = _SETTINGS.api_url
TIMEOUT = 120.0
# El host de la API de cartas es configuracion nuestra, no del modelo.
_IMAGE_EXTRA_HOSTS = tuple(
    host for host in (urlparse(_SETTINGS.mtg_api_base_url).hostname,) if host
)

EJEMPLOS = [
    "Que fases hay en un turno de juego?",
    "Como funciona el mana?",
    "Mi Rapaz del campo de batalla ha hecho dano con dana primero; si la cambio "
    "por mi Ninja de horas tardias, se aplica el dano?",
    "Busco una carta blanca de coste inferior a dos que sea guerrero",
    "Quiero una carta de Han Solo, blanca-roja, con dana primero",
]

st.set_page_config(page_title="Asistente MTG", page_icon="🃏", layout="centered")
st.title("🃏 Asistente de Magic: The Gathering")
st.caption("Reglas, interacciones, busqueda de cartas y cartas custom.")

if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = uuid.uuid4().hex
if "history" not in st.session_state:
    st.session_state.history = []


def _post_message(text: str) -> dict:
    response = httpx.post(
        f"{API_URL}/chat",
        json={"message": text, "conversation_id": st.session_state.conversation_id},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.subheader("Estado")
    try:
        health = httpx.get(f"{API_URL}/health", timeout=5.0).json()
        if health.get("status") == "ok":
            st.success(f"API viva - {health['rule_chunks']} fragmentos de reglas")
        else:
            st.warning(f"API degradada: {health.get('reason')}")
    except httpx.HTTPError:
        st.error(f"No hay API en {API_URL}")

    st.subheader("Prueba con")
    for ejemplo in EJEMPLOS:
        if st.button(ejemplo, use_container_width=True):
            st.session_state.pending = ejemplo

    if st.button("Nueva conversacion", type="primary", use_container_width=True):
        httpx.delete(
            f"{API_URL}/conversations/{st.session_state.conversation_id}", timeout=10.0
        )
        st.session_state.conversation_id = uuid.uuid4().hex
        st.session_state.history = []
        st.rerun()

MAX_IMAGENES = 5  # el mismo tope que el prompt de sistema pide para las busquedas


for entry in st.session_state.history:
    with st.chat_message(entry["role"]):
        st.markdown(entry["content"])
        # Las imagenes son lo unico que el texto de la respuesta no puede dar.
        # Solo http(s) a hosts de arte conocidos: st.image descarga la URL.
        con_imagen = []
        for carta in entry.get("cards", []):
            url = safe_card_image_url(
                carta.get("image_url"), extra_hosts=_IMAGE_EXTRA_HOSTS
            )
            if url:
                con_imagen.append((carta, url))
        if con_imagen:
            con_imagen = con_imagen[:MAX_IMAGENES]
            columnas = st.columns(len(con_imagen))
            for columna, (carta, url) in zip(columnas, con_imagen, strict=True):
                columna.image(url, caption=carta["name"])
        if entry.get("citations"):
            labels = ", ".join(c["label"] for c in entry["citations"])
            st.caption(f"Base: {labels}")
        if entry.get("trace"):
            with st.expander("Como lo he averiguado"):
                for call in entry["trace"]:
                    icon = "✅" if call["ok"] else "⚠️"
                    st.markdown(f"{icon} `{call['tool']}` - {call['summary']}")
                    st.json(call["arguments"], expanded=False)
        if entry.get("custom_card"):
            st.json(entry["custom_card"])

prompt = st.chat_input("Escribe tu duda...") or st.session_state.pop("pending", None)

if prompt:
    st.session_state.history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"), st.spinner("Consultando reglamento y cartas..."):
        try:
            data = _post_message(prompt)
        except httpx.HTTPError as exc:
            st.error(f"Error hablando con la API: {exc}")
        else:
            st.session_state.history.append(
                {
                    "role": "assistant",
                    "content": data["answer"],
                    "citations": data.get("citations", []),
                    "trace": data.get("trace", []),
                    "cards": data.get("cards", []),
                    "custom_card": data.get("custom_card"),
                }
            )
            st.rerun()
