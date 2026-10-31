# Envío — Hackathon Global de IA NVIDIA × Nebius

*[English](SUBMISSION.md) · Español*

**Proyecto:** La Fabrique — agentes de código con voz, sobre Nemotron en Nebius
Token Factory

**Categoría:** Programa de Ingeniería de Codificación y Agentes

**Licencia:** [Apache-2.0](LICENSE) para todo lo que se envía: la fábrica, la
fusión, la demo y el asistente (`asistente-b1/`), escrito desde cero para este
repositorio. `profesor3/`, una obra derivada de **MARK 56 — JARVIS** de
FatihMakes bajo [CC BY-NC 4.0](profesor3/LICENSE), queda como referencia y como
segunda interfaz opcional (`--asistente profesor3`); no forma parte del producto
que se distribuye.

| Campo del formulario | Valor |
|---|---|
| Repositorio público | `https://github.com/careb36/la-fabrique/tree/fusion` (rama `fusion`) |
| Demostración funcional | `python demo/coding_agent.py` (ver más abajo) + fábrica en `http://localhost:3000` |

---

## 1. Descripción del proyecto

**Qué es.** La Fabrique es una fábrica de software con ocho agentes —Product
Owner, Arquitecto, Scrum Master, Desarrollo, QA, SecOps, Documentación y
Memoria— que toma un requisito escrito y devuelve código con sus pruebas. Cada
rol tiene su propio modelo, su propio presupuesto de tokens y su propio turno de
conversación; el resultado no se acepta por lo que dice el modelo, se acepta
porque el intérprete lo ejecuta y las pruebas pasan.

Encima de eso hay un asistente de escritorio (Asistente B1) que **oye y habla**:
«fabricá el login», «¿cómo va el sprint?», «pausá el sprint». La fusión de los
dos proyectos añade a la fábrica una puerta de voz (`/v1/voice/*`) y al
asistente un plugin que la llama. Las órdenes habladas pasan por los mismos
endpoints que la interfaz web, así que una frase no puede hacer nada que la web
no permita. Habla en español y en inglés con el mismo motor: escucha con pistas
de idioma, contesta con Piper o con la voz del sistema, y la fábrica redacta su
respuesta en el idioma de la conversación.

**Por qué.** Los agentes de código suelen fallar de dos maneras: dicen que
terminaron sin haber ejecutado nada, o cuestan una fortuna porque cada llamada
va al modelo más grande. Este proyecto ataca las dos: el agente **ejecuta** las
pruebas de verdad y devuelve la salida al modelo cuando fallan, y el trabajo se
reparte entre tres niveles — Ultra para razonar, Super/Nano para el resto.

**Cómo funciona** (las tres piezas que se pueden ver funcionando):

1. `demo/coding_agent.py` — el bucle mínimo y completo: el modelo propone
   archivos en JSON, el agente los escribe en un directorio aislado, ejecuta
   `unittest` y, si algo falla, le pasa la salida real y repite.
2. `la-fabrique/` — el flujo multiagente (LangGraph) con Postgres, NATS y su
   `llm-proxy`, que valida cada modelo contra el catálogo del proveedor.
3. `asistente-b1/` — el asistente, escrito para este envío: fin de frase por
   energía, transcripción local (faster-whisper), Nemotron para pensar, Piper
   para hablar y tres herramientas que llaman a la puerta de voz de la fábrica.
   `profesor3/` queda como interfaz alternativa.

## 2. Cómo se usa NVIDIA Nemotron y Nebius Token Factory

- **Infraestructura:** `https://api.tokenfactory.nebius.com/v1` es la dirección
  por defecto de todo el proyecto (`profesor3/core/fabrica_env.py`,
  `la-fabrique/llm-proxy/app.py`). El `llm-proxy` consulta `GET /models` y
  rechaza cualquier id que el proveedor no esté sirviendo en ese momento.
- **Modelos abiertos de NVIDIA:** `nvidia/nemotron-3-ultra-550b-a55b` para
  razonamiento (PO, Arquitecto, SecOps y el agente de la demo) y
  `nvidia/nemotron-3-super-120b-a12b` / un Nano para las llamadas rápidas.
- **El reparto se escribe solo:** el panel **⚙ Nemotron** del asistente toma el
  catálogo real y escribe `NEMOTRON_ROLES`, `NEMOTRON_MODEL`,
  `NEMOTRON_MODEL_STRATEGIC` y `NEMOTRON_MODEL_FAST` en `la-fabrique/.env`.
  `la-fabrique/backend/llm/model_factory.py` los aplica por rol.
- **Por qué Token Factory aceleró el trabajo:** un único cliente compatible con
  OpenAI para ocho agentes, la demo y el asistente; catálogo como fuente de
  verdad (nada de ids inventados); y dos niveles de coste sobre el mismo
  proveedor.

## 3. Demostración funcional

```bash
git clone -b fusion https://github.com/careb36/la-fabrique.git fusion && cd fusion
export NEBIUS_API_KEY=nvapi-...        # Nebius Token Factory
python demo/coding_agent.py            # escribe, ejecuta, prueba, corrige
```

Salida real (Nemotron Ultra, Token Factory):

```
[ronda 1] Implemented slugify function with unicode normalization...
[ronda 1] escribió: slugify.py, test_slugify.py
[ronda 1] pruebas: OK (26.2s)

✅ las pruebas pasan (1 ronda(s), 26.2s)
```

Sin clave: `python demo/coding_agent.py --offline` hace el mismo recorrido con
dos respuestas grabadas (una ronda que falla, otra que arregla).

Para la fábrica completa, `cd la-fabrique && docker compose up -d` y abrir
<http://localhost:3000>; para el asistente, `arrancar.cmd` en Windows.

## 4. Guion del vídeo (3 minutos)

| Tiempo | Qué se ve |
|---|---|
| 0:00–0:20 | El problema en una frase: «un agente que dice que terminó». Se ve `demo/coding_agent.py --offline` fallando en la ronda 1 y pasando en la 2. |
| 0:20–0:50 | La demo con Token Factory de verdad: se ejecuta con la clave, se ve el id `nvidia/nemotron-3-ultra-550b-a55b` y las pruebas en verde. |
| 0:50–1:20 | `⚙ Nemotron` en el asistente: pegar la clave, **Probar clave**, `↻` para traer el catálogo, elegir Ultra y guardar. Se muestra el `.env` con los tres niveles. |
| 1:20–2:10 | La fábrica: requisito → agentes → sprint en el tablero, con los eventos de cada rol y el modelo que usó cada uno. |
| 2:10–2:40 | La voz: «B1, ¿cómo va el sprint?» y «pausá el sprint», con la respuesta hablada y el cambio en el tablero. |
| 2:40–3:00 | Cierre: `python tools/hackathon_check.py` en verde. |

## 5. Feedback

Está en el README, sección [Feedback para Nebius y NVIDIA](README.md#feedback-for-nebius-and-nvidia):
lo que funcionó (base_url único, catálogo consultable, niveles de coste) y las
tres fricciones reales (claves `nvapi-` indistinguibles entre puertas, modelos
retirados con `410`, y la ausencia de `/audio/transcriptions` para la voz).

## 6. Si el proyecto existía antes del período de envío

Sí: `la-fabrique` y `profesor3` son dos proyectos anteriores. El detalle de qué
se añadió durante el período está en
[Qué existía antes del hackathon](README.md#what-existed-before-the-hackathon).
En resumen: proveedor Nemotron con detección de puerta y migración de modelos
retirados, niveles Ultra/Super/Nano aplicados por rol, la puerta de voz, la demo
del agente y el verificador de requisitos.

## 6.1 Origen del código (transparencia)

| Pieza | Origen | Licencia |
|---|---|---|
| `la-fabrique/` | checkout upstream de la fábrica (FastAPI + React) | Apache-2.0 |
| `asistente-b1/` | escrito desde cero para este envío (2.382 líneas de código, 1.070 de pruebas) | Apache-2.0 |
| `profesor3/` | obra derivada de *MARK 56 — JARVIS*, de FatihMakes; referencia, no se distribuye | CC BY-NC 4.0 (`profesor3/LICENSE`) |
| Puerta de voz, guía hablada, proveedor Nemotron, demo y lanzador | escritos para este envío | Apache-2.0 |

El asistente que se envía es **Asistente B1** (`asistente-b1/`): se reescribió
completo —audio, modelo, herramientas, interfaz— para que el producto no dependa
de una licencia no comercial. La independencia se mide, no se declara:

```bash
cd asistente-b1 && python tools/similarity_check.py ../profesor3
# prosa: 0 coincidencias de 8 palabras · código: 0 bloques de 14 tokens
```

La prueba `tests/test_originality.py` incluye además un control positivo: si se
le pasa un párrafo copiado, el mismo chequeo lo detecta.

## 7. Checklist de la convocatoria

- [x] Proyecto funcional sobre Nebius Token Factory con un modelo abierto de NVIDIA
- [x] Categoría elegida (Programa de Ingeniería de Codificación y Agentes)
- [x] Descripción del proyecto (este documento)
- [x] Demostración funcional ejecutable (`demo/coding_agent.py`)
- [x] Demo que corre en local con un comando; no hay un despliegue compartido,
      porque el demonio del espacio de trabajo escribe en la carpeta de quien lo
      ejecuta
- [x] Vídeo de ≤ 3 minutos (guion en la sección 4)
- [x] Repositorio con licencia Apache-2.0 en la raíz; el asistente que se envía
      (`asistente-b1/`) también, y `profesor3/` conserva la CC BY-NC 4.0 de su
      upstream, declarada en la sección de licencia
- [x] README con instalación y guía de ejecución
- [x] Explicación de cómo se usan Nemotron y Token Factory
- [x] Feedback sobre Nebius y NVIDIA
- [x] Explicación de las actualizaciones del período de envío
- [x] `python tools/hackathon_check.py` verifica los puntos anteriores
