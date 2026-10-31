# La Fabrique XR — Meta VR Start Developer Competition 2026

What was added for the competition (Productivity track, Adapted division).
La Fabrique existed before the entry period (September 24, 2026); everything
listed here was built during it, in `xr/` and its workflow, and is new.

## 2026-10-31

- **`xr/`: La Fabrique XR on the Immersive Web SDK.** A seated,
  hands-first WebXR app (IWSDK 1.0.1) that opens in mixed reality
  (`immersive-ar`, passthrough) with hand tracking. Its first panel sits
  within a seated reach (`src/layout.ts`: every panel on an arc at 50 cm,
  below eye level, tested to stay inside 60 cm) and answers a pinch or a
  poke.
- **IWSDK's Quest 3 emulator on the published page**, so the experience can be
  tried in a desktop browser without a headset; the Quest browser skips it
  and runs real WebXR.
- **GitHub Pages deployment** (`.github/workflows/xr-pages.yml`): every push
  that touches `xr/` runs its tests, builds it and publishes it.
- **The room's model and the demo player** (`src/model.ts`,
  `src/demo/scenario.ts`, `src/engine/player.ts`). The room's state is built
  only from events shaped like the ones the backend publishes on the
  Glassroom stream. The demo replays three recorded tasks: a password reset
  that the risk tier holds for a person, a CSV export that QA closes after one
  rework, and a CI change held for a person. A person's approval closes a task;
  a rejection plays the rework and asks again. The player's clock moves only
  while it is not paused, so pause and resume are exact, and restart is the
  initial state; the whole demo runs in under ten minutes (tested).
- **The control room** (`src/ui/`, `src/main.ts`). A task panel (launch a
  task with a pinch or a poke), one panel per agent (Architect, Developer,
  QA, Verifier, ScrumMaster) with its state and latest output, a result
  panel with the delivery's diff, the Verifier's checks and the risk tier,
  where a person approves or sends it back, and the room's controls (pause,
  resume, restart) with its recent events. Everything a hand touches hangs
  on an arc at 45 cm; the agents, which only show, stand on one at 55 cm.
  Buttons are at least 4.5 cm tall for a fingertip. Taking the headset off
  or opening the system menu pauses the room, and coming back resumes it.
- **Live mode** (`src/live.ts`), optional: a build with `VITE_FABRIQUE_API`
  opened with `?sprint=<id>` (and a stream ticket when the backend requires
  authentication) follows a real sprint's Glassroom stream, mapping each
  event to its agent's panel. It only watches; decisions stay in the web app.
- **README for the judges** (`xr/README.md`): the hands-only path on a Quest,
  the desktop path, and how to try a local build on a headset.
- **Poke and pinch on every panel**: panels carry IWSDK's `PokeInteractable`
  (a fingertip crossing a button presses it) beside `RayInteractable`
  (pointing and pinching), so either way a hand works.
- **The room comes to the person**: on entering XR the panels are placed
  around wherever the head is and faces, sitting or standing
  (`around` in `src/layout.ts`, tested), and a **Recenter** button on the
  Room panel brings them back in front. Checked in IWSDK's Quest 3 emulator,
  where an emulated hand pointing at **Launch** and pinching starts the task.
