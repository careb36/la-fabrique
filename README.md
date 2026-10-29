# Fusión: La Fabrique + MARK LVI (asistente de voz)

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

## Arranque rápido

Requisitos: Python 3.11+ y las dependencias de cada mitad.

```bash
# 1) Entorno del backend (una vez, en la raíz del repo)
python -m venv .venv-backend
.venv-backend/bin/pip install poetry
(cd la-fabrique/backend && ../../.venv-backend/bin/poetry install)
# Windows: .venv-backend\Scripts\poetry install

# 2) Entorno del asistente (una vez)
python -m venv profesor3/.venv
profesor3/.venv/bin/pip install -r profesor3/requirements.txt
# Windows: profesor3\.venv\Scripts\pip install -r profesor3\requirements.txt

# 3) Arrancar todo
python run_fusion.py
```

`run_fusion.py` busca solo el intérprete correcto para cada mitad
(`.venv-backend/`, `profesor3/.venv/` y, si no, el que lo ejecuta). Si usas
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

## Qué se puede decir

| Frase | Acción |
|---|---|
| «¿Cómo va la fábrica?» / «estado del sprint» | Resumen del tablero: pendientes, en curso, en revisión, hechas, bloqueadas y entregas por aprobar. |
| «¿Qué equipo tengo?» | Lista de agentes y roles. |
| «Planea un sprint para el login con Google» | Vista previa del plan (no escribe nada). |
| «Crea un sprint para el login con Google» | Lo crea **en pausa** y lo dice. |
| «Reanuda la fábrica» | Los agentes empiezan a trabajar. |
| «Pausa la fábrica» | No se empieza nada nuevo. |
| «Despacha las tareas pendientes» | Manda a los agentes las tareas en `todo`. |
| «Aprueba la última entrega» / «recházala porque no cumple» | Registra la decisión en el expediente. |
| «¿Qué puedes hacer con la fábrica?» | Ayuda con el vocabulario. |

Todo se entiende también en inglés (`estado`, `crear_sprint`… con `language=en`).

### Por qué el sprint nace en pausa

Crear un sprint ya despacha trabajo a los agentes. Una confirmación del tipo
`confirm=true` la escribe el modelo, no la persona. Por eso la creación por voz
**pausa el sprint inmediatamente después de crearlo**: los agentes no empiezan
hasta que la persona dice «reanuda». Es una segunda orden explícita, no una
casilla que el modelo pueda rellenar solo.

## Configuración

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

## Seguridad

* Sin `VOICE_API_KEY` y con `AUTH_REQUIRED=true`, `/v1/voice/*` responde **503**:
  nunca se abre sola.
* Con clave, se exige en la cabecera `X-Voice-Key` (comparación en tiempo
  constante) o un JWT normal con rol suficiente.
* La clave se compara en el servidor; el asistente solo la guarda en
  `config/api_keys.json` (permisos 600 cuando el sistema lo permite).

## Pruebas

```bash
# Voz de la fábrica (sin Postgres, NATS ni LLM)
cd la-fabrique/backend
PYTHONPATH=.:app python -m pytest tests/test_voice_control.py -q

# Plugin del asistente (sin Qt ni audio)
cd profesor3
python -m unittest discover -s tests -q
```

## Limitaciones honestas

* **Ejecución autónoma completa** (agentes escribiendo archivos) necesita el
  resto de la pila: Postgres + NATS JetStream + el proxy LLM + el daemon de
  espacio de trabajo (`docker compose up -d postgres nats llm-proxy` y
  `scripts/start-daemon.sh`). El modo SQLite sirve para planear, crear,
  pausar/reanudar, ver el tablero y gobernar entregas; los `task.assign` quedan
  en el outbox hasta que haya NATS.
* La planificación usa el proxy LLM; sin él, el planificador cae en su lista
  determinista (4 tareas) y lo dice igual.
* Los sprints creados por voz se planifican con el objetivo dictado; ajusta
  tareas y prioridades desde la web si quieres afinar.
