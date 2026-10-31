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
- **Never a silent black screen**: the page says it is loading until the
  room draws its first frame; a browser without WebGL 2 (hardware
  acceleration off, a blocked GPU) is told so and what to try, and a room
  that fails to start says why.

## 2026-11-01

- **The factory lives on your desk and your wall** (`src/room.ts`,
  `src/surfaces.ts`). With plane and mesh detection, the room reads the
  person's real space: the panels a hand uses stand on the desk in front of
  them, leaning back toward the eyes, and the agents hang on the wall ahead
  as the team's board, larger for the distance. A desk counts when it is at
  desk height below the eyes and its near edge is within reach; a wall when
  it is ahead and within reading range (doors, windows and wall art never
  do). Whatever the room lacks falls back to the floating arc, so it works
  in any room. Recenter lays it out again. 37 tests.
- **A real-looking room in the emulator**: the published page's Quest 3
  emulator runs in a synthetic office, whose desk and walls are detected
  like a real room's, so the passthrough view and the video show a room
  rather than black.
- **The agents are presences in the room, and the task travels between
  them** (`src/ui/presence.ts`, `tokenAt` in `src/model.ts`). Each agent
  has a light in its own color above its panel, on the wall or on the
  arc: still while it waits, breathing with a turning ring while it works,
  a green flash when it finishes. The task is a glowing block that glides
  to whichever agent has it in hand and then down to the person's result
  panel, carrying the Verifier's confirmations as green seals that orbit
  it; a rework starts again with none. Unlit materials and a handful of
  meshes, to keep each frame cheap. 41 tests.
- **Deciding is a gesture** (`src/decide.ts`, `dropZone` in
  `src/ui/presence.ts`). When a delivery waits for the person, a green
  **Approve** ring and a red **Send back** ring appear beside it. The
  person pinches the delivery, carries it onto one and lets go; the ring
  under it lights up on the way. Released anywhere else it glides back, so
  a slip never decides. The panel's buttons remain as the alternative.
  Checked in the emulator with an emulated hand: pinch, carry, release on
  each ring. 44 tests.
- **Look at an agent to ask what it does** (`src/gaze.ts`). Half a second
  of the head resting on an agent's panel opens it: it grows and shows that
  agent's duty (the Verifier "observes what really happened: hashes the
  files on disk and runs the tests"). Head direction, not eye tracking, so
  it works on any headset; a glance opens nothing.
- **A guide for the first moves** (`src/guide.ts`, `src/ui/guide.ts`). An
  orange arrow, a ring and one line point at where each first move is
  made: Launch, then an agent to look at while they work, then the
  delivery to carry to a ring. It disappears once the person has decided
  once. Checked in the emulator, seated: each step shows in turn, and
  turning the head to the Verifier opens its panel. 54 tests.
- **High contrast** (`setContrast` in `src/ui/kit.ts`). A button on the
  Room panel turns every panel black with a white border, all text white,
  every button outlined; the layout does not move. Remembered on the
  device.
- **Voice as an alternative** (`src/voice.ts`). Where the browser has
  speech recognition, a Voice button listens for short commands in English
  or Spanish: approve, send it back, pause, resume, restart, recenter, and
  launch a task by a word of its title or its place ("launch the CSV
  export", "lanzar la primera"). A send back always wins over an approval
  in the same sentence, and the Room panel shows what it heard and what it
  did. Without speech recognition the button is not shown. Checked in the
  emulator with a stand-in recognizer: the spoken launch started the task.
  59 tests.
- **The company learns, across sessions** (`src/learning.ts`). Each run of
  the demo is a sprint. When every task is done it closes: its rework is
  counted from its own events (QA's NEEDS WORK, a person's send back), and
  each task that needed rework adopts a procedure; the next sprint plays
  with the procedure in force, and the Developer's first delivery already
  covers what was asked. A panel with the team draws rework per task by
  sprint and lists the procedures and who taught each one; the ScrumMaster
  announces the close. Kept on the device, so the curve continues the next
  time the page opens; New company starts over. Checked in the emulator:
  sprint 1 with a send back closes at 0.67 rework per task with two
  procedures, sprint 2 at 0.00. 63 tests.

## 2026-11-02

- **Sound from where it happens** (`src/sound.ts`). Short synthesized
  chimes, no audio files: each agent has its own note, its start and finish
  sound from its light on the wall (spatial, HRTF), the Verifier's seals
  ring, a delivery waiting for the person chimes from the result panel,
  approve and send back answer, a closed sprint plays a short arpeggio.
  At most one sound a second on average. Mute on the Room panel or by
  voice ("mute", "silencio"), remembered on the device.
- **Each agent wears its color**: a strip on its panel in the same color as
  its light.
- **Render cost measured, and kept low**: foveated rendering on; a render
  budget script (`npm run budget`) enters XR in the emulator, runs the demo
  to its busiest moment and reads 118 draw calls and about 48,000
  triangles per frame, against a budget of 200 and 150,000.
- **A frame meter in the room** (`src/perf.ts`): with `?perf`, the Room
  panel shows frames per second, the 95th percentile frame time, the share
  of slow frames and the draw calls, measured live on the device that runs
  it. Built without a headset, the frame rate on a Quest was not measured;
  the README says so. 74 tests.
