# Submission — NVIDIA × Nebius Global AI Hackathon

**Project:** La Fabrique — voice-driven coding agents on Nemotron, served by
Nebius Token Factory

**Category:** Coding & Agents Engineering Program

**License:** [Apache-2.0](LICENSE) for everything submitted: the factory, the
fusion, the demo and the assistant (`asistente-b1/`), written from scratch for
this repository. `profesor3/`, a derivative work of **MARK 56 — JARVIS** by
FatihMakes under CC BY-NC 4.0, is a separate reference checkout and an optional
second front end (`--asistente profesor3`); it is not in this repository and is
not part of the product that ships.

| Form field | Value |
|---|---|
| Public repository | `https://github.com/careb36/la-fabrique/tree/fusion` (`fusion` branch) |
| Working demo | `python demo/coding_agent.py` (see below) + the factory at `http://localhost:5173` |

---

## 1. Project description

**What it is.** La Fabrique is a software factory with eight agents — Product
Owner, Architect, Scrum Master, Developer, QA, SecOps, Technical Writer and
Memory — that takes a written requirement and returns code with its tests. Each
role has its own model, its own token budget and its own turn in the
conversation. A result is not accepted because the model says it is done. In
the demo it is accepted when the interpreter runs the tests and they pass; in
the factory, when the files the workspace daemon wrote match the delivery and
QA answers `APPROVED:` (with `DELIVERY_TESTS_ENABLED=true`, the project's tests
must pass too).

On top of that sits a desktop assistant (Assistant B1) that **listens and
speaks**: "build the login", "how is the sprint going?", "pause the sprint".
The fusion of the two projects gives the factory a voice door (`/v1/voice/*`)
and the assistant a plugin that calls it. Spoken commands go through the same
endpoints as the web UI, so a sentence cannot do anything the web does not
allow. It speaks Spanish and English with the same engine: it listens with
language hints, answers with Piper or the system voice, and the factory writes
its reply in the language of the conversation.

**Why.** Coding agents tend to fail in two ways: they say they finished without
running anything, or they cost a fortune because every call goes to the largest
model. This project tackles both: the agent really **runs** the tests and feeds
the output back to the model when they fail, and the work is split across three
tiers — Ultra for reasoning, Super/Nano for the rest.

**How it works** (the three pieces you can see running):

1. `demo/coding_agent.py` — the minimal, complete loop: the model proposes files
   as JSON, the agent writes them into an isolated directory, runs `unittest`
   and, if anything fails, hands the real output back and tries again.
2. `la-fabrique/` — the multi-agent flow (LangGraph) with Postgres, NATS and its
   `llm-proxy`, which checks every model against the provider's catalogue.
3. `asistente-b1/` — the assistant, written for this submission: end of speech
   detected by Silero VAD (loudness as the fallback), local transcription (faster-whisper), Nemotron to think,
   Piper to speak, and three tools that call the factory's voice door.
   `profesor3/` remains an alternative front end.

## 2. How NVIDIA Nemotron and Nebius Token Factory are used

- **Infrastructure:** `https://api.tokenfactory.nebius.com/v1` is the default
  endpoint of the factory's proxy (`NEBIUS_PROXY_URL` in
  `la-fabrique/llm-proxy/app.py`) and of the demo (`demo/nemotron.py`). The
  `llm-proxy` queries `GET /models` and refuses any id missing from the
  provider's catalogue.
- **NVIDIA open models:** `nvidia/nemotron-3-ultra-550b-a55b` for reasoning (PO,
  Architect, SecOps and, by default, the demo agent) and
  `nvidia/nemotron-3-super-120b-a12b` / a Nano model for the fast calls.
- **The split is configuration:** `NEMOTRON_ROLES`, `NEMOTRON_MODEL`,
  `NEMOTRON_MODEL_STRATEGIC` and `NEMOTRON_MODEL_FAST` live in
  `la-fabrique/.env` (`.env.example` ships them with every role opted in), and
  `la-fabrique/backend/llm/model_factory.py` applies them per role. The
  reference assistant's **⚙ Nemotron** panel can write them from the live
  catalogue; that assistant is not distributed here.
- **Why Token Factory sped up the work:** a single OpenAI-compatible client for
  eight agents, the demo and the assistant; the catalogue as the source of
  truth (no invented ids); and two cost tiers on the same provider.

## 3. Working demo

```bash
git clone -b fusion https://github.com/careb36/la-fabrique.git fusion && cd fusion
export NEBIUS_API_KEY=nvapi-...        # Nebius Token Factory
python demo/coding_agent.py            # writes, runs, tests, fixes
```

Real output (Nemotron Ultra, Token Factory; the demo prints in Spanish):

```
[ronda 1] Implemented slugify function with unicode normalization...
[ronda 1] escribió: slugify.py, test_slugify.py
[ronda 1] pruebas: OK (26.2s)

✅ las pruebas pasan (1 ronda(s), 26.2s)
```

Without a key, `python demo/coding_agent.py --offline` makes the same run with
two recorded answers (a round that fails, then one that fixes it).

For the full factory, `cd la-fabrique && docker compose up -d` and open
<http://localhost:5173>; for the assistant, `arrancar.cmd` on Windows or
`python run_fusion.py` elsewhere.

## 4. Video script (3 minutes)

| Time | What is shown |
|---|---|
| 0:00–0:20 | The problem in one sentence: "an agent that says it finished". `demo/coding_agent.py --offline` fails in round 1 and passes in round 2. |
| 0:20–0:50 | The demo against the real Token Factory: it runs with the key, the id `nvidia/nemotron-3-ultra-550b-a55b` is visible and the tests go green. |
| 0:50–1:20 | `⚙ Nemotron` in the reference assistant (`profesor3`, not distributed): paste the key, **Test key**, `↻` to fetch the catalogue, pick Ultra and save. The `.env` with the three tiers is shown. |
| 1:20–2:10 | The factory: requirement → agents → sprint on the board, with each role's events and the model each one used. |
| 2:10–2:40 | The voice: "B1, how is the sprint going?" and "pause the sprint", with the spoken answer and the change on the board. |
| 2:40–3:00 | Closing: `python tools/hackathon_check.py` all green. |

## 5. Feedback

It is in the README, section [Feedback for Nebius and NVIDIA](README.md#feedback-for-nebius-and-nvidia):
what worked (a single base_url, a queryable catalogue, cost tiers) and the three
real points of friction (`nvapi-` keys that look the same for both gateways,
retired models answering `410`, and no `/audio/transcriptions` for voice).

## 6. Did the project exist before the submission period?

Yes: `la-fabrique` and `profesor3` are two earlier projects. What was added
during the period is detailed in
[What Existed Before the Hackathon](README.md#what-existed-before-the-hackathon).
In short: the Nemotron provider with gateway detection and migration of retired
models, Ultra/Super/Nano tiers applied per role, the voice door, the agent demo
and the requirements checker.

## 6.1 Where the code comes from (transparency)

| Piece | Origin | License |
|---|---|---|
| `la-fabrique/` | upstream checkout of the factory (FastAPI + React) | Apache-2.0 |
| `asistente-b1/` | written from scratch for this submission (about 4,300 lines of code, 2,400 of tests) | Apache-2.0 |
| `profesor3/` | derivative work of *MARK 56 — JARVIS* by FatihMakes; reference only, not distributed | CC BY-NC 4.0 |
| Voice door, spoken guide, Nemotron provider, demo and launcher | written for this submission | Apache-2.0 |

The assistant that ships is **Assistant B1** (`asistente-b1/`). It was
rewritten end to end — audio, model, tools, interface — so the product does not
depend on a non-commercial license. Its independence is measured, not claimed:

```bash
cd asistente-b1 && python tools/similarity_check.py ../profesor3
# … prosa: 0 coincidencias de 8 palabras · código: 0 bloques de 14 tokens
```

(The tool prints in Spanish: 0 prose matches of 8 words, 0 code blocks of 14
tokens.)

The test `tests/test_originality.py` also includes a positive control: given a
copied paragraph, the same check catches it.

## 7. Submission checklist

- [x] Working project on Nebius Token Factory with an NVIDIA open model
- [x] Category chosen (Coding & Agents Engineering Program)
- [x] Project description (this document)
- [x] Runnable working demo (`demo/coding_agent.py`)
- [x] Demo that runs locally in one command; there is no shared deployment,
      because the workspace daemon writes to the folder of the person running it
- [x] Video of ≤ 3 minutes (script in section 4)
- [x] Repository with the Apache-2.0 license at the root; the assistant that
      ships (`asistente-b1/`) too, and `profesor3/` keeps its upstream
      CC BY-NC 4.0, declared in the license section
- [x] README with installation and run guide
- [x] Explanation of how Nemotron and Token Factory are used
- [x] Feedback on Nebius and NVIDIA
- [x] Explanation of the updates made during the submission period
- [x] `python tools/hackathon_check.py` verifies the license, the README, the
      Token Factory and Nemotron defaults, the offline demo and that no `.env`
      is tracked (and, with a key, the provider and its catalogue)
