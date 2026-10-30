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

### Windows (PowerShell)

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
```

### Si algo falla en Windows

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

### macOS / Linux

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

## Qué se puede decir

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
