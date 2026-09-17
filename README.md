# Turing Challenge

Resolución de los ejercicios del reto. Cada ejercicio vive en su propia
carpeta, con su código, sus tests y su documentación.

| Ejercicio | Enunciado | Estado |
|---|---|---|
| [1 — Asistente de Magic: The Gathering](ejercicio-1-mtg/) | Chatbot para un call center: reglas, interacciones entre cartas, búsqueda de cartas y creación de cartas custom | ✅ |
| [2 — Revisión de código](ejercicio-2-code-review/code_review.md) | Auditoría de un pipeline RAG ajeno (OpenAI + Chroma) y versión mejorada razonada | ✅ |

---

## Ejercicio 1

Asistente conversacional que combina un **RAG sobre el reglamento oficial** con
la **API pública de cartas**, dentro de un agente que decide qué consultar y
mantiene el hilo de la conversación. Cada respuesta llega con sus citas y con la
traza de las herramientas usadas, de forma que siempre se puede justificar.

Corre sobre **Claude en Amazon Bedrock** con el perfil de inferencia `eu.`, de
modo que la inferencia no sale de la UE; la API de primera parte de Anthropic
queda a dos variables de entorno de distancia.

- **[Documento de solución productiva](ejercicio-1-mtg/docs/01-arquitectura-produccion.md)** — servicios, tipos de agente, evaluación, observabilidad, residencia del dato y costes, con diagramas.
- **[Decisiones técnicas](ejercicio-1-mtg/docs/02-decisiones-tecnicas.md)** — qué se descartó y por qué.
- **[Demo ejecutable](ejercicio-1-mtg/README.md)** — FastAPI + Streamlit, 149 tests sin red ni secretos.
  Hay un [GIF de la demo](ejercicio-1-mtg/docs/assets/demo.gif) grabado contra Bedrock real, con las cuatro capacidades del enunciado.

```bash
cd ejercicio-1-mtg
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ingest]"
pytest
```

---

## Ejercicio 2

Revisión de un pipeline de ingesta y consulta escrito por otra persona. El
código de partida no arranca con una instalación actual de `openai`, pierde
documentos en cuanto se ingesta dos veces y lleva la clave de API en el fuente.

- **[Análisis y código mejorado](ejercicio-2-code-review/code_review.md)** — 15
  hallazgos clasificados por severidad, la versión corregida comentada, y qué
  se ha dejado deliberadamente fuera.

La versión mejorada **sigue en OpenAI** a propósito: cambiar de proveedor no es
un hallazgo de revisión, y mezclar una migración con los arreglos ocultaría
cuáles eran los problemas reales.

---

## Licencia

MIT — ver [LICENSE](LICENSE).
