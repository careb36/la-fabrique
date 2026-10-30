# La Fabrique — agentes de código con voz, sobre Nemotron en Nebius Token Factory

**Licencia [Apache-2.0](LICENSE)** · Categoría: **Coding & Agents Engineering** ·
Hackathon Global de IA NVIDIA × Nebius

Una fábrica de software con ocho agentes que **escriben, ejecutan y prueban
código**, y un asistente de voz que la dirige con la boca — «Fabricá el login»,
«¿cómo va el sprint?», «pausá». Lo que razona corre en **Nebius Token Factory**
con los modelos abiertos de NVIDIA: **Nemotron 3 Ultra** para lo que exige
pensar y **Super/Nano** para las llamadas del día a día.

Todo lo que hay aquí funciona: el agente de la demo escribe una función, corre
las pruebas en un intérprete de verdad, lee el fallo y se corrige sola. No hay
un vídeo que lo cuente mejor que la salida real:

```console
$ python demo/coding_agent.py --offline
[ronda 1] first pass: lower-case and dashes
[ronda 1] escribió: slugify.py, test_slugify.py
[ronda 1] pruebas: FALLAN — Ran 3 tests in 0.001s | FAILED (failures=2)
[ronda 2] second pass: fold accents and drop punctuation
[ronda 2] escribió: slugify.py
[ronda 2] pruebas: OK (0.1s)

✅ las pruebas pasan (2 ronda(s), 0.2s)
```

## Qué construimos

Dos piezas que se hablan entre sí, más el puente que las une:

| Pieza | Qué es | Dónde |
|---|---|---|
| **La Fábrica** | Flujo multiagente (LangGraph) que toma un requisito y lo lleva a código con pruebas: PO → Arquitecto → Scrum → Desarrollo → QA → SecOps → Documentación. FastAPI + React + Postgres + NATS. | `la-fabrique/` |
| **MARK LVI** | Asistente de escritorio (PyQt6): escucha, piensa y habla. También ejecuta acciones y lee las respuestas en voz alta. | `profesor3/` |
| **La fusión** | Endpoints `/v1/voice/*` en la fábrica + plugin en el asistente, y el proveedor Nemotron que hace que el asistente piense con el mismo modelo que los agentes. | `run_fusion.py`, `plugins/fabrica.py` |

El bucle que pide la categoría —**escribir, ejecutar, probar**— está en tres
sitios, y los tres son código que corre de verdad:

1. **`demo/coding_agent.py`** — el bucle completo en un archivo: el modelo
   devuelve archivos, el agente los escribe en un directorio de trabajo, ejecuta
   `unittest` y, si falla, le pasa la salida real al modelo y repite.
2. **La fábrica** — cada rol es un agente con su propio modelo y su propio
   presupuesto de tokens; el resultado se ejecuta y se prueba antes de darse por
   terminado.
3. **La voz** — el asistente crea el sprint, lo pausa y pregunta por el estado
   hablando, a través de la misma API que usa la interfaz web (una orden hablada
   no puede hacer nada que la web no permita).
4. **La frase** — «hacé una página sencilla en html, css, javascript con la
   fábrica»: el modelo devuelve los archivos, la fábrica los escribe en disco y
   los sirve en una URL que el asistente abre y comenta. Es el bucle de la
   categoría, disparado hablando.

### De una frase a una página abierta

El camino es corto y todo ocurre en el mismo proceso que ya corre:

1. El asistente reconoce el pedido (`plugins/fabrica.py`, `looks_like_build_request`)
   y llama a `POST /v1/voice/build` con la frase limpia.
2. La fábrica pide el proyecto al modelo que le toca al rol *Developer* por el
   `llm-proxy`, con presupuesto de tokens propio y un reintento de reparación si
   el modelo contesta prosa en vez de JSON (`app/services/codegen.py`).
3. Los archivos se escriben en `FABRICA_BUILDS_DIR` (por defecto `/workspace/builds`)
   bajo un slug con fecha, sin poder salir de esa carpeta.
4. `GET /v1/voice/build/<slug>/<archivo>` los sirve sandboxeados, y el asistente
   abre esa URL en el navegador y dice qué hizo, en cuánto tiempo y con cuántos
   archivos.

Si el modelo falla, la respuesta es `ok: false` con una frase para leer en voz
alta — nunca un 500.

## Cómo usa Nemotron y Nebius Token Factory

**Token Factory es la infraestructura**, no un extra: la dirección por defecto de
todo el proyecto es `https://api.tokenfactory.nebius.com/v1`, y el `llm-proxy`
de la fábrica valida cada id contra el catálogo vivo del proveedor antes de
enviar una petición (un modelo retirado falla en la puerta, con su motivo, en
vez de a mitad de un sprint).

**Nemotron reparte el trabajo según lo que cuesta pensar:**

| Nivel | Variable | Modelo | Para quién |
|---|---|---|---|
| Razonamiento | `NEMOTRON_MODEL_STRATEGIC` | `nvidia/nemotron-3-ultra-550b-a55b` | PO, Arquitecto, SecOps, y el agente de la demo |
| Equipo | `NEMOTRON_MODEL` | el que elijas del catálogo | Desarrollo, QA, Scrum, memoria |
| Rápido | `NEMOTRON_MODEL_FAST` | `nvidia/nemotron-3-super-120b-a12b` o un Nano | Documentación y llamadas cortas |

Los tres niveles se escriben en `la-fabrique/.env` desde el panel **⚙ Nemotron**
del asistente, tomados del catálogo que el proveedor devuelve en ese momento:
nunca se inventa un id. El reparto no es una idea nuestra — es lo que recomienda
la convocatoria, y aquí está implementado en `NEMOTRON_ROLES` /
`NEMOTRON_MODEL_STRATEGIC` / `NEMOTRON_MODEL_FAST` (ver
`la-fabrique/backend/llm/model_factory.py`).

Lo que Token Factory nos ahorró, en concreto:

- **Un solo cliente.** Los ocho agentes, el asistente y la demo hablan
  `/v1/chat/completions` contra la misma dirección; no hay ocho integraciones.
- **Catálogo como fuente de verdad.** `GET /models` nos deja listar modelos en el
  panel y comprobar antes de gastar un turno.
- **Dos niveles, un proveedor.** Ultra para pensar, Super/Nano para responder:
  el mismo crédito rinde mucho más que usando un solo modelo para todo.
- **Streaming.** El asistente empieza a hablar antes de que la frase esté escrita.

> La app también acepta **NVIDIA NIM** (`integrate.api.nvidia.com`), que sirve
> los mismos Nemotron: las claves de las dos puertas empiezan por `nvapi-` y no
> se distinguen a ojo, así que el panel prueba ambas y se queda con la que
> acepta la clave. Para el envío del hackathon se usa Token Factory.

## Cómo ejecutar

### 1. La demo del agente (lo más rápido, 30 segundos)

```bash
git clone <este-repositorio> && cd fusion
export NEBIUS_API_KEY=nvapi-...          # Token Factory
python demo/coding_agent.py --task "slugify con pruebas unittest"
```

Sin clave, `--offline` hace el mismo recorrido con dos respuestas grabadas.

### 2. La fábrica completa

```bash
cd la-fabrique
cp .env.example .env                     # NEBIUS_API_KEY=... y NEBIUS_PROXY_URL
docker compose up -d                     # Postgres, NATS, backend, proxy, frontend
```

La interfaz queda en <http://localhost:3000> y la API en
<http://localhost:8000/docs>.

### 3. El asistente de voz (Windows)

```powershell
.\arrancar.cmd       # crea los entornos que falten y arranca fábrica + asistente
```

Requisitos: Python 3.12 con *Add python.exe to PATH*. El detalle de lo que hace
el lanzador —y qué hacer si falla— está en [Arranque rápido](#arranque-rápido).

### Comprobar que el repositorio cumple la convocatoria

```bash
python tools/hackathon_check.py                       # licencia, README, demo
NEBIUS_API_KEY=nvapi-... python tools/hackathon_check.py   # + proveedor y modelos
```

## La demo y el vídeo

`demo/coding_agent.py` es la demostración funcional: se ejecuta en una terminal,
termina con las pruebas en verde y no necesita nada más que una clave. El guion
del vídeo de tres minutos, los enlaces de envío y las respuestas a las preguntas
del formulario están en **[SUBMISSION.md](SUBMISSION.md)**.

## Pruebas

```bash
python -m pytest tests -q                     # 86 pruebas del repositorio
cd profesor3 && python -m unittest discover -s tests   # 155 del asistente
python tools/hackathon_check.py               # los requisitos del envío
cd la-fabrique && make test                   # backend, proxy y frontend
```

## Feedback para Nebius y NVIDIA

Lo que nos ayudó y lo que nos costó, con el detalle de lo que pasó:

- **A favor:** un `base_url` compatible con OpenAI para todos los Nemotron, y un
  `/models` que se puede consultar antes de gastar crédito. El reparto
  Ultra/Super/Nano es real: bajar las llamadas cortas a Super se nota en la
  factura y no en la calidad.
- **Fricción 1 — claves indistinguibles.** Las claves de Token Factory y de
  NVIDIA NIM empiezan por `nvapi-`, y un 401 dice «Couldn't authenticate» en
  ambos casos: no se puede saber si la clave es mala o si es de la otra puerta.
  Nos costó una tarde; ahora el panel prueba las dos y lo explica. Un campo
  `provider` en la respuesta de error lo resolvería.
- **Fricción 2 — modelos que se retiran.** `llama-3.3-nemotron-super-49b-v1`
  contestó `410 Gone` con el id guardado en la configuración. Un encabezado de
  deprecación (o `sunset`) en `/models` permitiría migrar antes de romperse; hoy
  lo resolvemos consultando el catálogo y reintentando con el reemplazo.
- **Fricción 3 — no hay `/audio/transcriptions`.** El asistente necesitaba voz y
  ninguna de las dos puertas la ofrece, así que la transcripción es local
  (`faster-whisper`, que el arranque instala sola). Está bien documentarlo como
  «texto», pero conviene decirlo en la portada: es la primera cosa que alguien
  intenta.
- **NVIDIA Nemotron:** cumple el protocolo de JSON que pide el agente de código
  mejor de lo esperado (archivos completos, sin fences, en la primera ronda) y
  escribe pruebas que de verdad fallan cuando el código está mal. El modo
  «thinking» mejora el plan y añade latencia; para voz lo apagamos.

## Qué existía antes del hackathon

Para que el jurado pueda separar lo nuevo de lo que ya estaba:

**Antes** — `la-fabrique` (fábrica multiagente con FastAPI/React/Postgres/NATS,
sus ocho roles y su `llm-proxy`) y `profesor3` (asistente de escritorio PyQt6 con
voz, plugins y tablero) eran dos proyectos funcionando por separado, atados a
Gemini y a un reparto de modelos Qwen/DeepSeek.

**Durante el período de envío** — se hizo la fusión y todo lo que hace falta para
que corra sobre Token Factory:

1. **Proveedor Nemotron en el asistente** (`profesor3/providers/llm_openai.py`),
   con detección de puerta, catálogo y migración automática de un id retirado.
2. **Niveles Ultra/Super/Nano** escritos desde el panel y aplicados por rol en la
   fábrica (`core/fabrica_env.py`, `la-fabrique/backend/llm/model_factory.py`).
3. **Puerta de voz** `/v1/voice/*` + plugin del asistente: la fábrica se maneja
   hablando (`la-fabrique/backend/app/routers/voice.py`, `plugins/fabrica.py`).
4. **`demo/coding_agent.py`**: el bucle escribir → ejecutar → probar, aislado y
   reproducible.
5. **`tools/hackathon_check.py`**: los requisitos de la convocatoria como
   pruebas ejecutables.
6. Correcciones nacidas de usar el modelo de verdad: migración ante `410`,
   claves del `.env` que no llegaban al encabezado, y la instalación automática
   de `faster-whisper` para que el asistente no arranque sordo.

---

## El producto en detalle


Dos programas, un solo producto:

* **`la-fabrique/`** — la fábrica de software con agentes (FastAPI + React).
* **`profesor3/`** — MARK LVI / Tutor Virtual A1, el asistente de escritorio que
  oye, habla y ejecuta acciones (Gemini Live, PyQt6).

La fusión añade una **puerta de voz** a la fábrica (`/v1/voice/*`) y un **plugin**
en el asistente (`plugins/fabrica.py`). El asistente entiende la frase, llama a
la fábrica y lee en voz alta la respuesta. La fábrica sigue siendo la misma:
los endpoints de voz son un adaptador fino sobre los que ya usa la interfaz web,
así que una orden hablada no puede hacer nada que la web no permita.

```
   🎙  "¿cómo va la fábrica?"
            │
     MARK LVI (Gemini Live)  ──►  plugins/fabrica.py
            │                            │  POST /v1/voice/command
            │                            ▼
            │                     FastAPI  /v1/voice/*
            │                     (start_sprint, pause_sprint, …)
            ▼                            │
   🔊 "Sprint 12 «Login» va …"  ◄────────┘
```

### Arranque rápido

#### Windows (PowerShell)

Requisitos: **Python 3.12** (probado con 3.12.10) instalado con *Add
python.exe to PATH*. Se acepta 3.11+, pero el script busca 3.12 primero, incluso
si el `python` del sistema es otra versión.

```powershell
cd "C:\Users\Felipe\projects\fusion"
.\arrancar.cmd
```

Qué hace, en orden:

1. localiza Python 3.12 por **varias vías independientes** —`py --list-paths`,
   el registro de Windows, las carpetas `Python3*` de `%LOCALAPPDATA%\Programs\Python`
   y `Program Files`, la base con la que se crearon los entornos (`pyvenv.cfg`)
   y `python3.12` del PATH— y comprueba con cada candidato que responde de
   verdad: las sondas se ejecutan en un proceso aparte y se releen sus archivos
   de salida, con reintento si llegasen vacíos;
2. reutiliza `.venv-backend` y `profesor3\.venv` si existen y funcionan
   (en Windows el intérprete es `Scripts\python.exe`; `bin/python` solo en
   Linux/macOS);
3. crea únicamente lo que falte; si una carpeta está dañada la mueve a
   `.venv-backend.roto-<fecha>` en vez de borrarla;
4. instala solo si hace falta: `poetry install` y, si Poetry no alcanza PyPI,
   pip con las **versiones exactas de `poetry.lock`** (`tools/lock_requirements.py`);
5. verifica los módulos esenciales y distingue «falta» de «está roto»,
   mostrando el traceback completo;
6. arranca backend y asistente, comprueba que la API responde y para los dos
   con Ctrl+C.

Todo queda en `logs\arranque-<fecha>.log`.

Si Windows bloquea el script («la ejecución de scripts está deshabilitada»),
usa cualquiera de estas dos formas:

```powershell
powershell -ExecutionPolicy Bypass -File .\arrancar.ps1
# o doble clic en arrancar.cmd
```

Opciones:

```powershell
.\arrancar.ps1 -Instalar          # comprueba y completa dependencias + pip check
.\arrancar.ps1 -Reinstalar        # mueve los entornos a *.roto-<fecha> y los rehace
.\arrancar.ps1 -Preparar          # solo deja los entornos listos, sin arrancar
.\arrancar.ps1 -SoloBackend       # solo la API de la fábrica
.\arrancar.ps1 -SoloAsistente     # el asistente contra una API ya viva
.\arrancar.ps1 -Puerto 8123       # otro puerto (si el 8000 está ocupado)
.\arrancar.ps1 -Python "C:\ruta\python.exe"   # intérprete concreto
.\arrancar.ps1 -Diagnostico       # qué intérpretes ve y cuál elegiría, sin instalar nada
.\arrancar.ps1 -Url http://127.0.0.1:8000 -Clave <clave> -Empresa "Mi estudio"
.\arrancar.ps1 -Completa          # fábrica completa: agentes que ejecutan (necesita Docker)
.\arrancar.ps1 -Completa -Agentes "D:\trabajo\agentes"   # y dónde escriben
.\arrancar.ps1 -InterfazWeb       # además compila la UI React de la fábrica (Node)
```

#### Solo el círculo en el escritorio

El asistente puede vivir como un único botón flotante, sin consola:

```powershell
profesor3\boton-flotante.cmd                       # doble clic
.\profesor3\dist\AI-Workspace.exe --floating      # el ejecutable, sin ventana
```

Arranca directo en el orbe (`--floating`); clic derecho → *Abrir consola*,
*Generar con la fábrica*, *Quitar el modo flotante* o *Salir*. La fábrica se
controla desde ahí por voz («¿cómo va la fábrica?», «crea un sprint para…»,
«despacha las tareas») o desde el panel que abre *Generar con la fábrica*.

#### El ejecutable empaquetado (`profesor3\dist`)

`profesor3\dist\AI-Workspace.exe` es el asistente **congelado** con PyInstaller:
una copia del código del día en que se compiló. Si después cambia el diseño, ese
`.exe` sigue mostrando la apariencia anterior. El lanzador ya no lo usa (arranca
desde el código, con el aspecto nuevo), pero si lo abres por tu cuenta verás la
cara vieja hasta que lo regeneres:

```powershell
.\regenerar-ejecutable.cmd      # o doble clic sobre el .cmd
.\arrancar.cmd -Recompilar      # recompila (si hace falta) y arranca
```

En cada arranque el lanzador comprueba si el `.exe` es anterior al código y te
avisa con el comando exacto. La comprobación a mano es
`python profesor3\tools\build_exe.py --check` (0 al día, 1 no existe, 2 más
viejo que el código).

#### Fábrica completa (`-Completa`)

Sin nada más, el producto sirve para **mandar la fábrica por voz**: crear el
sprint, despacharlo, pausarlo, aprobarlo y verlo en el tablero. Los agentes,
en cambio, no ejecutan tareas: sin broker ni base de datos sus encargos se
quedan en la cola.

`-Completa` levanta la infraestructura con Docker Desktop y arranca el demonio
de trabajo, que es lo que convierte "despachar" en ficheros escritos:

```powershell
.\arrancar.ps1 -Completa
```

1. `docker compose up -d postgres nats llm-proxy` en `la-fabrique/`;
2. rellena lo que el compose necesita en `la-fabrique/.env` (contraseña de
   Postgres, `JWT_SECRET_KEY`, y `GEMINI_API_KEY` tomada del propio asistente),
   una sola vez y sin tocar lo que ya estuviera escrito;
3. espera a los puertos 5432, 4222 y 5100 y apunta el backend a ellos;
4. arranca `vscode-daemon` en nativo sobre la carpeta `agentes\` (también
   con `-SoloBackend`: el demonio no necesita ventana).

Los agentes escriben **solo** dentro de `agentes\` (o de la carpeta que pases
con `-Agentes`). Si no hay Docker, el arranque se para y lo dice: preferimos
eso a un tablero que promete ejecución y no la tiene.

Con una sola clave (la de Gemini del asistente) todos los roles usan el mismo
modelo: el mapa de roles de la fábrica mezcla ids de Qwen y DeepSeek, y sin sus
claves el proxy los rechazaría como «modelo desconocido» y las tareas quedarían
bloqueadas. Por eso `-Completa` exporta `AGENT_MODEL=gemini-flash-latest` cuando
no hay `QWEN_API_KEY` ni `DEEPSEEK_API_KEY`; si añades esas claves a
`la-fabrique/.env`, el mapa vuelve a mandar. Para forzar otro modelo, pon
`AGENT_MODEL=<id>` en `la-fabrique/.env`.

#### Si algo falla en Windows

Todo queda en `logs\arranque-<fecha>.log`. Los avisos `!!` son recuperables; los
`XX` paran el arranque antes de dejar el producto a medias.

| Síntoma | Causa | Qué hace el lanzador |
|---|---|---|
| `All attempts to connect to pypi.org failed` en Poetry | Poetry solo confía en `certifi`; pip y PowerShell usan el almacén de certificados de Windows (antivirus/proxy con inspección TLS) | exporta las raíces del sistema a `logs\windows-ca-bundle.pem`, reintenta y, si sigue fallando, instala con pip las versiones de `poetry.lock` |
| Lo mismo **y pip tampoco descarga** | sin red, DNS caído o proxy que no responde | imprime el veredicto (DNS, HTTPS a pypi, `pip download` de prueba y proxy configurado) y, si el entorno del asistente ya trae `httpx`, `annotated-types`, `distro`, `sniffio`…, los copia al backend para arrancar sin red |
| `langchain-core requires httpx … which is not installed` | instalación anterior interrumpida | detecta los módulos que faltan y completa solo esos |
| `no se puede ejecutar un documento en medio de una canalización: …\bin\python` | ruta de venv de Linux usada en Windows | en Windows solo se acepta `Scripts\python.exe` |
| `NativeCommandError` al comprobar módulos | PowerShell 5.1 convierte el stderr de Python en error | las comprobaciones se ejecutan sin pasar por el pipeline y se informa «falta» o «roto» con su traceback |
| Se usaba Python 3.13/3.14 | el `python` del PATH no es el 3.12 | busca `py -3.12` y la ruta del usuario antes de caer a otra versión |
| `Necesito Python 3.11 o superior` aunque esté instalado | la sonda no devolvía salida (carrera al leer la redirección) y parecía que ningún intérprete servía | se espera a que el proceso cierre del todo, se reintenta la sonda en el propio proceso y, si aun así falla, se acepta la ruta que declaran `pyvenv.cfg`, el registro o `py --list-paths`; `-Diagnostico` muestra candidato por candidato qué pasó |

Comandos de diagnóstico (opcionales):

Si el arranque dice «Backend utilizable con los módulos prestados», la fábrica
funciona pero esos módulos salieron del entorno del asistente. Cuando vuelvas a
tener internet, `\.\arrancar.ps1 -Instalar` los sustituye por los del lock.

```powershell
.\arrancar.ps1 -Preparar -SoloBackend        # deja el entorno listo y sale
.\arrancar.ps1 -Diagnostico                  # intérpretes detectados y elegido
.venv-backend\Scripts\python.exe -m pip check
.venv-backend\Scripts\python.exe -c "import fastapi, httpx, langchain_core"
.venv-backend\Scripts\python.exe -m uvicorn app.main:app --port 8999   # con PYTHONPATH=.;app
Get-Content (Get-ChildItem logs\arranque-*.log | Sort-Object LastWriteTime | Select-Object -Last 1)
```

#### macOS / Linux

```bash
python -m venv .venv-backend
.venv-backend/bin/pip install poetry
(cd la-fabrique/backend && ../../.venv-backend/bin/poetry install)

python -m venv profesor3/.venv
profesor3/.venv/bin/pip install -r profesor3/requirements.txt

python run_fusion.py
```

`run_fusion.py` busca solo el intérprete correcto para cada mitad
(`.venv-backend/`, `la-fabrique/backend/.venv`, `profesor3/.venv` y, si
existe, el entorno que ya creó Poetry con `poetry env info --path`). Si usas
otros entornos, pásalos:

```bash
python run_fusion.py --backend-python /ruta/al/python --assistant-python /ruta/al/python
```

Y hace el resto:

1. carga `la-fabrique/.env` (lo ya exportado manda);
2. si no hay Postgres configurado, usa **SQLite** en `la-fabrique/.fusion/factory.db`
   — la fábrica funciona sin infraestructura;
3. desactiva Neo4j en ese modo (`NEO4J_DISABLED=true`) para que el arranque no
   espere a un bolt que no existe;
4. genera una `VOICE_API_KEY` y la comparte con el asistente;
5. crea la empresa inicial con su equipo la primera vez;
6. escribe la URL y la clave en `profesor3/config/api_keys.json`
   (sección `plugin_config.fabrica`);
7. arranca el asistente y para las dos piezas con Ctrl+C.

Opciones útiles:

```bash
python run_fusion.py --backend-only      # solo la API (para la web)
python run_fusion.py --assistant-only    # el asistente contra una API ya viva
python run_fusion.py --url http://127.0.0.1:8124   # puerto libre, misma máquina
python run_fusion.py --url http://otra:8000 --voice-key <clave> --no-config
python run_fusion.py --company "Mi estudio"
```

La primera vez que abras el asistente te pedirá la `gemini_api_key` como
siempre; la configuración de la fábrica ya estará puesta.

### Qué se puede decir

| Frase | Acción |
|---|---|
| «¿Cómo va la fábrica?» / «estado del sprint» | Resumen del tablero: pendientes, en curso, en revisión, hechas, bloqueadas y entregas por aprobar. |
| «¿Qué sprints tengo?» | Los últimos cinco, del más nuevo al más viejo, con su estado. |
| «¿Qué equipo tengo?» | Lista de agentes y roles. |
| «Planea un sprint para el login con Google» | Vista previa del plan (no escribe nada). |
| «Crea un sprint para el login con Google» | Lo crea **en pausa** y lo dice. |
| «Reanuda la fábrica» | Los agentes empiezan a trabajar. |
| «Pausa la fábrica» | No se empieza nada nuevo. |
| «Despacha las tareas pendientes» | Manda a los agentes las tareas en `todo`. |
| «Aprueba la última entrega» / «recházala porque no cumple» | Registra la decisión en el expediente. |
| «Abre la fábrica» / «muéstrame la fábrica» | Abre el tablero de la fábrica en el navegador. |
| «Hacé una página sencilla en html, css y javascript con la fábrica» | El modelo arma el proyecto, queda escrito en disco, se sirve en una URL y el asistente la abre y lo cuenta. |
| «Fabricá una calculadora» | Igual, con el pedido que digas: la frase después del disparador es el requisito. |
| «¿Qué puedes hacer con la fábrica?» | Ayuda con el vocabulario. |

Todo se entiende también en inglés (`estado`, `crear_sprint`… con `language=en`).

#### Por qué el sprint nace en pausa

Crear un sprint ya despacha trabajo a los agentes. Una confirmación del tipo
`confirm=true` la escribe el modelo, no la persona. Por eso la creación por voz
**pausa el sprint inmediatamente después de crearlo**: los agentes no empiezan
hasta que la persona dice «reanuda». Es una segunda orden explícita, no una
casilla que el modelo pueda rellenar solo.

### El tablero de la fábrica

Al arrancar, el lanzador abre el **panel del asistente** (`http://127.0.0.1:8770`),
que es la cara nueva del producto y lleva la fábrica dentro, en su pestaña
**Fábrica** (desactívalo con `--no-browser` o `-SinNavegador`). En el propio
equipo el panel entra sin clave: el servidor inyecta una sesión local en la
página solo cuando la petición viene de loopback. Desde otro dispositivo manda
la clave de emparejamiento de *Control remoto*, como siempre.

Si el asistente no llega a arrancar, el lanzador abre directamente la fábrica
con la sesión ya abierta: el token viaja en el fragmento (`#sesion=…`), que no
llega al servidor ni a los registros, y la propia aplicación lo borra de la
barra de direcciones en cuanto lo adopta. También se llega por voz («abre la
fábrica») y con el botón **Fábrica** del asistente.

El panel web del asistente (`http://127.0.0.1:8770`, la clave de emparejamiento
aparece en *Control remoto*) tiene una pestaña **Fábrica** que muestra la
interfaz React de la fábrica **tal cual, embebida**. `GET /fabrica` es una
puerta: pide una sesión a `/v1/auth/desktop` con la clave que el asistente ya
tiene y redirige con `#sesion=…`. Como es otro origen, el backend declara
`FRAME_ANCESTORS` (loopback, cualquier puerto) para que el iframe no se quede
en blanco; sin esa variable `X-Frame-Options: DENY` lo bloquea.

Las órdenes que das con los botones del panel viajan al asistente, no a la
fábrica:

```
navegador  --(token)-->  /api/fabrica/command  --(X-Voice-Key)-->  /v1/voice/command
```

Así la clave compartida de la fábrica nunca llega al navegador, y el tablero
usa exactamente el mismo vocabulario que la voz: si una frase funciona
hablando, el botón también.

### Configuración

En `la-fabrique/.env`:

```ini
VOICE_API_KEY=<secreto compartido>   # el asistente lo envía como X-Voice-Key
VOICE_COMPANY_ID=                    # vacío = la primera empresa
DATABASE_URL=sqlite:///./factory.db  # opcional; sin esto, Postgres
AUTH_REQUIRED=false                  # solo instalación local de un usuario
```

En el asistente, ⚙ → plugins → **FÁBRICA — control por voz**:

* URL del backend (por defecto `http://127.0.0.1:8000`)
* `VOICE_API_KEY`
* ID de empresa (opcional)
* idioma de las respuestas (`auto` sigue el idioma del asistente)

El botón **PROBAR CONEXIÓN** llama a `/v1/voice/ping` y dice si la clave vale.

### Seguridad

* Sin `VOICE_API_KEY` y con `AUTH_REQUIRED=true`, `/v1/voice/*` responde **503**:
  nunca se abre sola.
* Con clave, se exige en la cabecera `X-Voice-Key` (comparación en tiempo
  constante) o un JWT normal con rol suficiente.
* La clave se compara en el servidor; el asistente solo la guarda en
  `config/api_keys.json` (permisos 600 cuando el sistema lo permite).

### Pruebas

```bash
# Voz de la fábrica (sin Postgres, NATS ni LLM)
cd la-fabrique/backend
PYTHONPATH=.:app python -m pytest tests/test_voice_control.py -q

# Plugin del asistente y tablero (sin Qt ni audio)
cd profesor3
python -m unittest discover -s tests -q

# Lanzador (no abre ventanas ni arranca la fábrica)
python -m pytest tests -q
```

### Limitaciones honestas

* **Ejecución autónoma completa** (agentes escribiendo archivos) necesita el
  resto de la pila: Postgres + NATS JetStream + el proxy LLM + el daemon de
  espacio de trabajo. Eso es exactamente `-Completa`; sin Docker el modo SQLite
  sirve para planear, crear, pausar/reanudar, ver el tablero y gobernar
  entregas, pero los `task.assign` quedan en el outbox hasta que haya NATS.
* La planificación usa el proxy LLM; sin él, el planificador cae en su lista
  determinista (4 tareas) y lo dice igual.
* Los sprints creados por voz se planifican con el objetivo dictado; ajusta
  tareas y prioridades desde la web si quieres afinar.
