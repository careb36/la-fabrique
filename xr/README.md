# La Fabrique XR

A seated, hands-first mixed-reality control room for La Fabrique's agents,
built with the [Immersive Web SDK](https://iwsdk.dev) (WebXR). You hand a
task to the agents, watch each of them work on its own panel, read what
they delivered and what the Verifier observed, and approve it or send it
back, all with your hands and within arm's reach.

**Try it:** <https://careb36.github.io/la-fabrique/>. No account, no keys,
no backend: the page runs a self-contained demo of recorded agent runs.

## For the judges

### On a Meta Quest (hands only)

1. Open the link above in the Quest browser and select **Enter XR**. The
   room opens in mixed reality (passthrough), placed around your head at
   arm's length, sitting or standing. Nothing needs you to stand or move.
2. Put the controllers down. Hand tracking takes over; every action is a
   **poke** (touch a button with a fingertip) or a **pinch** (point and
   pinch thumb and index finger).
3. On the **Tasks** panel (left), launch **Password reset endpoint**.
4. Watch the agents on the panels above: the Architect writes a brief, the
   Developer delivers, the Verifier checks what was really written to disk
   and runs the tests, QA reviews. About thirty seconds.
5. The **Result** panel (ahead) shows the diff, the Verifier's checks and the
   risk tier: authentication is high risk, so the delivery waits for you.
   The delivery itself, a glowing block above the panel, is yours to take:
   pinch it, carry it onto the red **Send back** ring and let go. The agents
   rework it and ask again. Then drop it on the green **Approve** ring. The
   buttons on the panel do the same, for anyone who prefers to poke.
6. **CSV export** shows a low-risk task that QA closes on its own after one
   rework; **Pin the CI runner** is another high-risk change for you to decide.
7. The **Room** panel (right) pauses, resumes and restarts the demo, and
   **Recenter** brings the panels back in front of you. Taking the headset
   off or opening the system menu pauses it too.

The whole demo takes under five minutes.

### In a desktop browser

The published page carries IWSDK's Quest 3 emulator, so the whole demo runs
without a headset. The room shows in the browser and every button works
with the mouse. **Enter XR** at the top starts an emulated Quest 3 session:
the emulator's toolbar switches between controllers and hands, and its
panels move the emulated head and hands and pinch. This is also how to
record the demo video without a headset (the rules accept a video filmed in
the XR Simulator).

## Live mode (optional)

The demo needs nothing. To watch a real sprint instead, build with the
backend's address and open the page with the sprint's id:

```bash
VITE_FABRIQUE_API=https://your-backend.example npm run build
# then open  <page>/?sprint=12          (backend with AUTH_REQUIRED=false)
#       or   <page>/?sprint=12&ticket=… (a stream ticket from
#            POST /v1/sprints/12/stream_ticket, valid five minutes)
```

The room then follows the sprint's Glassroom stream (`GET /v1/glassroom/stream`):
each agent's panel and the room's log update as the factory works. Live
mode only watches: tasks start, and decisions are taken, in the web app,
where a Manager signs in. The backend must list the page's origin in
`CORS_ORIGINS`.

## What it shows

| Panel | What it is |
|---|---|
| Tasks | three sample tasks; launch one with a pinch or a poke |
| Agents (5) | Architect, Developer, QA, Verifier and ScrumMaster: state and latest output |
| Result | the delivery's diff, the Verifier's checks, the risk tier, Approve / Send back |
| Room | pause, resume, restart, and the room's recent events |

The demo replays runs scripted from how La Fabrique's task worker runs a
task (`backend/app/services/task_worker.py`): the Architect's brief, the
Developer's delivery, the Verifier's deterministic checks of the files the
workspace daemon wrote, QA's review, and the risk tier that holds
high-risk work (authentication, secrets, payments, CI) for a person. The
room's events have the shape of the backend's Glassroom stream.

## Your room is the workspace

In passthrough the room reads your space (WebXR plane and mesh detection
through IWSDK's scene understanding). The panels you use with your hands
stand on **your desk**, leaning toward you; the agents hang on **the wall
ahead** as the team's board. A desk counts when it is within reach of a
seated person; a wall when it is ahead and readable. Whatever your room
lacks falls back to a floating arc, and **Recenter** lays it out again.
The Room panel says where it went.

## Design for a seated person

- Everything a hand touches hangs on an arc 45 cm from the head, just below
  eye level (`src/layout.ts`; a test keeps every panel within 60 cm).
  The agents' panels only show, and stand on an arc at 55 cm.
- Buttons are at least 4.5 cm tall, sized for a fingertip.
- Deciding is a gesture: the delivery is taken in hand with a pinch (near
  or from across the desk) and dropped on a ring 17 cm to either side of it
  (`src/decide.ts`). Released anywhere else it glides back, so a slip never
  decides. The panel's buttons stay as the alternative.
- No locomotion, no moving the panels by hand, nothing behind you.
- The room's clock moves only while it is not paused, so pause and resume
  are exact; restart returns to the initial state.

## Develop

```bash
cd xr
npm install
npm run dev        # https://localhost:5173 with the Quest 3 emulator
npm run test:run   # unit tests
npm run build      # static site in dist/
```

Requires Node.js 20.19 or later. To try a local build on a Quest, serve it
on your network (`npm run dev -- --host`) and open the address the terminal
prints from the Quest browser; accept the self-signed certificate.

| Path | What it holds |
|---|---|
| `src/model.ts` | the room's state, built only from events |
| `src/demo/scenario.ts` | the recorded tasks |
| `src/engine/player.ts` | plays them on a pausable clock |
| `src/live.ts` | live mode: the backend's Glassroom stream as room events |
| `src/ui/` | the panels |
| `src/layout.ts` | where panels go around a seated person |
| `src/room.ts`, `src/surfaces.ts` | the desk and wall from the room's detected surfaces |
| `src/main.ts` | the IWSDK world |

What is new for the Meta VR Start Developer Competition is listed in
[`CHANGELOG_COMPETITION.md`](../CHANGELOG_COMPETITION.md).
