# Decisiones técnicas de la demo

Registro corto de las decisiones que no son obvias, con su alternativa y el
motivo del descarte. Sirve para que el revisor no tenga que reconstruirlas
leyendo el código.

---

### D1 — Bucle agéntico manual en vez del Tool Runner del SDK

**Alternativa**: `client.beta.messages.tool_runner()`, que resuelve el bucle solo.

**Decisión**: bucle manual sobre `messages.create`.

**Por qué**: se necesitaba (a) inyectar un doble del cliente LLM para que la
suite corra sin red ni API key, (b) capturar la traza de cada herramienta para
enseñársela al usuario como respaldo, y (c) no meter una API beta en el camino
crítico. El bucle son ~60 líneas y están testadas.

---

### D2 — BM25 propio en vez de embeddings

**Alternativa**: embeddings + vector store.

**Decisión**: BM25 implementado en el repositorio (`rag/index.py`), con un
glosario ES↔EN para expandir la consulta.

**Por qué**: el corpus es pequeño y el vocabulario cerrado y muy técnico, que es
donde lo léxico rinde. Además es determinista, así que los tests pueden fijar
rankings exactos, y no cuesta nada por consulta. El punto ciego —el cliente
escribe "daña primero" y el reglamento dice "first strike"— se tapa con el
glosario, y hay un test que lo demuestra.

BM25 puro, eso sí, se queda corto en preguntas amplias: "mana" aparece en medio
reglamento, su IDF es casi cero y el ranking lo deciden reglas de esquina. Se
midió (`scripts/eval_retrieval.py`) y se corrigió con dos señales, no con
intuición — ver D10.

**Cuándo cambiarlo**: en producción, híbrido BM25 + denso con re-ranker. El
cambio está contenido en una sola clase.

---

### D3 — La unidad de chunk es la regla numerada

**Por qué**: la numeración del reglamento ("702.7b") es a la vez el límite
semántico natural y **la unidad de cita que el cliente puede verificar**. Trocear
por ventanas de tokens rompe las dos cosas a la vez. Cuando el documento no está
numerado, el chunker detecta el caso y cae a ventanas de párrafos con solape,
citando por página.

---

### D4 — Los rangos de coste se filtran en cliente

La API de `magicthegathering.io` solo acepta `cmc` **exacto**; no hay operadores
de rango. Como "coste inferior a dos" es una de las consultas del enunciado, el
cliente pagina candidatos y filtra en memoria (`_matches_cmc_range`), acotado por
`mtg_api_max_pages` para no disparar la latencia. Está documentado en el propio
módulo y cubierto por tests.

---

### D5 — La carta custom se valida en código, no en el prompt

El modelo propone; `tools/designer.py` valida notación del coste, coherencia
color↔coste, fuerza/resistencia solo en criaturas, y respalda cada palabra clave
con una regla del reglamento. Si algo falla, devuelve un `tool_result` de error y
el modelo corrige. Pedirle al prompt que "valide" produce cartas plausibles pero
incorrectas; una regla determinista no.

---

### D6 — Prompt de sistema y catálogo de herramientas estables

El orden de renderizado de la petición es `tools → system → messages`. El prompt
es texto constante (sin fechas ni IDs) y `ALL_TOOLS` es una tupla ordenada, de
modo que el prefijo cacheable no cambia entre turnos. Hay dos tests que lo fijan
como contrato, porque es el tipo de regresión que nadie nota hasta que llega la
factura.

---

### D7 — Un fallo de herramienta no tumba el turno

Herramienta inexistente, argumentos inválidos o excepción se convierten en un
`tool_result` con `is_error: true` y el bucle continúa: el modelo lee el error y
reformula. Solo un error de infraestructura sube como 5xx. Cada camino tiene su
test.

---

### D8 — La UI habla con la API por HTTP

Streamlit podría instanciar el agente en proceso y ahorrarse un salto. Se hace
por HTTP para que la demo ejercite el **mismo contrato** que usaría el canal real
del call center, y para que `ANTHROPIC_API_KEY` viva solo en el backend.

---

### D9 — Cada respuesta lleva su traza

`ChatResponse` incluye `citations` (para el cliente) y `trace` (qué herramienta
se llamó, con qué argumentos y con qué resultado). El enunciado pide que el bot
pueda **justificar** su respuesta; la traza es esa justificación, y de paso es el
material de observabilidad descrito en el documento de arquitectura.

---

### D10 — Dos correcciones sobre BM25, medidas y no adivinadas

Sobre las *Comprehensive Rules* reales, BM25 puro daba **38 % de `recall@6`**
contra el golden set de 16 preguntas. Dos señales lo subieron al **62 %**:

1. **Peso del título de sección** (`SECTION_TITLE_WEIGHT = 2`). "106. Mana" es
   señal de altísima precisión sobre de qué va el fragmento; sus términos cuentan
   varias veces. Es una aproximación a BM25F por campos.
2. **Prior de la regla general** (`TOP_LEVEL_RULE_PRIOR = 1.5`). En el reglamento,
   "509.1" enuncia el caso general y "509.1a" cubre una esquina. Ante una
   pregunta amplia la definitoria es casi siempre la respuesta.

Ambos valores se eligieron de un barrido y están **en una meseta, no en un
pico**: mover el peso entre 2 y 3, o el prior entre 1,3 y 1,8, no cambia el
resultado. Con 16 casos, eso importa más que el óptimo exacto — un pico sería
sobreajuste al golden set.

El 38 % restante no se arregla con más trucos léxicos: es el argumento concreto
para el recuperador híbrido con re-ranker del documento de arquitectura.

---

### D11 — El reglamento no se versiona

Las *Comprehensive Rules* son material con copyright de Wizards of the Coast. El
PDF vive en `data/raw/` (ignorado por git) y el índice es un artefacto
reproducible que se regenera con un comando. Como consecuencia,
`test_retrieval_quality.py` se salta en CI y solo corre en local, donde sí hay
reglamento.

---

### D12 — Bedrock por defecto, y las capacidades derivadas del modelo

**Decisión**: el proveedor por defecto es **Claude en Amazon Bedrock** con el
perfil de inferencia `eu.`, usando la cadena estándar de credenciales AWS. La
API de primera parte queda como segunda opción, a dos variables de distancia.

**Por qué**: no es un cambio de `base_url`. En Bedrock **el encargado del
tratamiento es AWS**, no Anthropic, y el perfil `eu.` mantiene la inferencia
dentro de la UE repartida entre seis regiones de estados miembro. Para un call
center que procesa consultas de clientes europeos, esa es la postura correcta.

**La trampa**: el proveedor no es lo único que cambia — cambia la **forma de la
petición**, y no por el proveedor sino por el modelo. Haiku 4.5 (el modelo por
defecto en Bedrock, ~la mitad de coste que Sonnet 5) devuelve **400** si recibe
`thinking: {type: "adaptive"}` o `output_config.effort`; Sonnet 5 y la familia
Opus 4.6+ los necesitan para rendir. Si eso se hubiera resuelto con un `if
provider == "bedrock"`, apuntar `MTG_MODEL` a Sonnet 5 en Bedrock habría
desperdiciado el razonamiento en silencio.

Por eso `capabilities_for()` deriva las capacidades **del id del modelo**, no
del proveedor, y reconoce igual el id corto (`claude-haiku-4-5`) que el datado
de Bedrock (`eu.anthropic.claude-haiku-4-5-20251001-v1:0`). Cambiar de modelo es
una variable de entorno, no un cambio de código, y hay tests que fijan los dos
casos.

**Lo que sigue siendo un cambio de código**: el `cache_control` explícito sobre
el bloque de sistema. La integración clásica de Bedrock rechaza el
`cache_control` de nivel superior con un 400, así que el breakpoint va anotado a
mano — que es lo que ya hacía D6 por otras razones.

---

### D13 — El `.env` se carga solo, pero el entorno manda

Ni `uvicorn` ni `streamlit` leen un `.env` por su cuenta, así que arrancar la
demo era un ritual de `export $(grep -v '^#' .env | xargs)` que además se come
mal los valores con espacios. La config lo carga al importarse.

Lo que importa es la **precedencia**: una variable que ya esté en el entorno
gana al fichero, nunca al revés. En local eso significa que un `MTG_MODEL=...`
puntual en la línea de comandos funciona; en CI y en contenedores significa que
un `.env` que se cuele en la imagen **no puede pisar** las credenciales reales
inyectadas por el orquestador. La precedencia contraria es la que convierte un
fichero olvidado en un incidente.

El `.env` en sí nunca se versiona: está en `.gitignore` y el repositorio es
público.

---

### D14 — Las cartas se ven, y su arte se descarga con lista blanca

El texto de una respuesta puede describir una carta, pero no *enseñarla*. Las
herramientas de cartas ya devolvían un `payload` estructurado que se quedaba a
medio camino: nadie lo consumía. Ahora `ChatResponse` lleva `cards`, y la UI
pinta el arte de las que lo tengan (hasta cinco, el mismo tope que el prompt de
sistema pide para las búsquedas).

Eso abre un frente que el resto de la demo no tenía: **`st.image(url)` la
descarga el proceso de Streamlit**. El `image_url` viene de un tercero
(`api.magicthegathering.io`), así que es una URL que elige alguien de fuera y
que pedimos nosotros — la definición de un SSRF. Un `file:///etc/passwd` o un
`http://169.254.169.254/latest/meta-data/` los pediría la UI, desde dentro de
la red.

Por eso `images.py` filtra contra una **lista blanca de hosts de arte**
(`gatherer.wizards.com`, que es lo que devuelve la API real, más los de
Scryfall) y solo admite `http`/`https`. El filtro usa `hostname` y no `netloc`,
que es lo que corta `https://gatherer.wizards.com@evil.example/x.png`, y exige
que el sufijo empiece por punto, que es lo que corta
`https://gatherer.wizards.com.evil.example/x.png`.

El host de `MTG_API_BASE_URL` se añade a la lista a propósito: es configuración
del operador, del mismo nivel de confianza que las credenciales. La lista
protege de lo que devuelve la API, no de quién despliega.

En producción esto no es un módulo de la UI sino una salida más por el
guardarraíl de egreso — ver `01-arquitectura-produccion.md`, sección 3.2.

---

### D15 — Los defaults son un fichero versionado, no literales en el código

Los valores por defecto estaban escritos en `config.py`, mezclados con la
lógica que los lee. Eso tiene dos problemas: cambiar el modelo por defecto es un
cambio de código Python, y ver *qué* está configurado obliga a leer una clase.

Ahora viven en [`config/defaults.toml`](../config/defaults.toml) y `Settings`
solo declara **qué campos existen, de qué tipo son y quién gana**:

```
variable de entorno  >  config/defaults.toml  >  default declarado en el campo
```

El default del campo pasa a ser una red de seguridad —solo actúa si alguien
borra la clave del fichero—, no la fuente de verdad.

**Por qué TOML y no JSON.** El valor que más falta hace explicar es el id de
Bedrock: sus tres partes (`eu.`, `anthropic.`, la fecha) son obligatorias y cada
una se descubrió con un 400 distinto. En JSON esa explicación no cabe, y habría
que dejarla en otro fichero, lejos del valor que justifica. TOML admite
comentarios, `tomllib` es stdlib desde 3.11 y el `pyproject` ya es TOML: cero
dependencias nuevas por el formato.

**Por qué `pydantic-settings`.** Sustituye a cuatro helpers escritos a mano
(`_env_str`, `_env_int`, `_env_path` y el reparto de precedencias) por un orden
de fuentes declarado. Se conservan las dos reglas que ya estaban probadas: una
variable **definida pero vacía** se trata como no definida y cae al TOML
(`_EnvSourceSinBlancos`), y el `.env` se vuelca a `os.environ` antes de nada
porque **boto3 lee de ahí**, no de nuestro modelo.

**La trampa que esto casi introduce, y por la que hay tests.** Con
`extra="ignore"`, un TOML cuyas claves no casen con los campos se ignora **en
silencio**: no hay error, los valores siguen siendo plausibles y el fichero
simplemente ha dejado de tener efecto. Pasó al montarlo —faltaba
`populate_by_name=True`, así que los campos solo respondían a su alias en
MAYÚSCULAS— y no se vio hasta cambiar un valor a propósito para comprobar si
viajaba. `tests/test_config.py` fija justo eso: que cada clave del fichero llega
a `Settings`, y que ninguna se descarta sin avisar.
