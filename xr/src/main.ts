import {
  createSystem,
  PokeInteractable,
  RayInteractable,
  SessionMode,
  UIKitDocument,
  VisibilityState,
  World,
} from '@iwsdk/core';
import { Object3D, Vector3 } from 'three';

import { DEMO_TASKS } from './demo/scenario';
import { Player } from './engine/player';
import { arc, around, type Placement } from './layout';
import { connectLive, liveConfig } from './live';
import { ROLES } from './model';
import { agentPanel, controlPanel, resultPanel, taskPanel, type Panel } from './ui/panels';

/** Seated eye height above the floor. */
const HEAD_Y = 1.2;

const container = document.getElementById('scene-container') as HTMLDivElement;
const notice = document.getElementById('notice') as HTMLDivElement;

/** Replace the loading notice with what went wrong and what to try. */
function fail(title: string, hint: string): never {
  notice.className = 'error';
  notice.replaceChildren();
  const p = document.createElement('p');
  const strong = document.createElement('strong');
  strong.textContent = title;
  p.append(strong, document.createElement('br'), hint);
  notice.append(p);
  throw new Error(title);
}

// The scene needs WebGL 2. Without it (hardware acceleration off, a blocked
// GPU) the page would stay black, so say so instead.
if (!document.createElement('canvas').getContext('webgl2')) {
  fail(
    'This browser cannot draw 3D (WebGL 2 is off).',
    'Turn on hardware acceleration in the browser settings, or open the link in a recent Chrome or Edge, or on a Meta Quest.',
  );
}

const world = await World.create(container, {
  xr: {
    // Mixed reality: the room stays visible around the panels.
    sessionMode: SessionMode.ImmersiveAR,
    offer: 'always',
    features: { handTracking: true },
  },
  // The desktop view only: a step back from the seat so every panel fits on
  // a screen. In a headset, tracking puts the camera at the person's eyes.
  render: { fov: 75, camera: { position: [0, HEAD_Y + 0.05, 0.42], lookAt: [0, HEAD_Y - 0.08, -0.45] } },
  features: { grabbing: false, locomotion: false, physics: false },
}).catch((error: unknown) =>
  fail('The room did not start.', `${error instanceof Error ? error.message : String(error)}. Try reloading the page.`),
);

// Live mode follows a real sprint when the build names a backend
// (VITE_FABRIQUE_API) and the address a sprint (?sprint=); otherwise the demo.
const live = liveConfig(import.meta.env.VITE_FABRIQUE_API, location.search);
const tasks = live
  ? [{ id: 'live', title: `Sprint ${live.sprintId}`, summary: 'Live from the factory', script: [] }]
  : DEMO_TASKS;
const player = new Player(tasks);
let previous = VisibilityState.NonImmersive as VisibilityState;
/** Paused by the headset (system menu, headset off), not by the person. */
let autoPaused = false;

const panels: Panel[] = [];
let dirty = true;
const touch = () => {
  dirty = true;
};

const placed: { object: Object3D; at: Placement }[] = [];

function place(p: Panel, at: Placement): void {
  // Both ways a hand presses a button: a fingertip crossing it (poke) and a
  // pinch while pointing at it (ray). Either works with controllers too.
  const entity = world.createTransformEntity().addComponent(RayInteractable).addComponent(PokeInteractable);
  entity.object3D!.add(new UIKitDocument(p.root));
  placed.push({ object: entity.object3D!, at });
  panels.push(p);
}

/** Put every panel around a head at `head`, facing `yaw` (radians). */
function arrange(head: Vector3, yaw: number): void {
  for (const { object, at } of placed) {
    const p = around(at, head, yaw);
    object.position.set(p.x, p.y, p.z);
    object.rotation.set(0, p.yaw, 0);
  }
}

const SEATED_HEAD = new Vector3(0, HEAD_Y, 0);
/** Set when the room should move to where the person's head is. */
let recenter = false;

/** Where the head is and which way it faces, from the camera. */
function headPose(): { head: Vector3; yaw: number } {
  const head = new Vector3();
  const forward = new Vector3();
  world.camera.getWorldPosition(head);
  world.camera.getWorldDirection(forward);
  return { head, yaw: Math.atan2(-forward.x, -forward.z) };
}

// Everything a hand touches hangs from one arc at 45 cm, just below eye
// level: tasks on the left, the result ahead, the room's controls on the right.
const [left, center, right] = arc(3, 96, 0.45, 0.04);
place(
  taskPanel(
    tasks,
    (id) => {
      if (player.launch(id)) touch();
    },
    live ? 'Watching the factory: tasks start from the web app.' : undefined,
  ),
  left,
);
place(
  resultPanel((id, approved) => {
    if (player.decide(id, approved, approved ? '' : 'add a test for a reused token')) touch();
  }, live ? 'Live mode watches: approve or send back in the web app.' : undefined),
  center,
);
place(
  controlPanel({
    onPause: () => {
      if (player.paused) player.resume();
      else player.pause();
      autoPaused = false;
      touch();
    },
    onRecenter: () => {
      recenter = true;
    },
    onRestart: () => {
      player.restart();
      // Live mode clears the view; the sprint itself goes on.
      if (live) player.ingest({ type: 'task_state', taskId: 'live', state: 'in_progress' });
      touch();
    },
  }),
  right,
);
// The agents only show, so they stand on a slightly farther arc just above it.
arc(ROLES.length, 100, 0.55, 0).forEach((at, i) => place(agentPanel({ ...player.state.agents[ROLES[i]] }), at));
arrange(SEATED_HEAD, 0);

// Leaving the headset or opening the system menu pauses the room; coming
// back resumes it, unless the person had paused it themselves.
world.visibilityState.subscribe((v) => {
  // Entering XR: the room moves to wherever the person's head is, sitting or
  // standing. Leaving it: back to the seated view of the desktop page.
  if (v === VisibilityState.Visible && previous === VisibilityState.NonImmersive) recenter = true;
  if (v === VisibilityState.NonImmersive) arrange(SEATED_HEAD, 0);
  previous = v;
  const away = v === VisibilityState.Hidden || v === VisibilityState.VisibleBlurred;
  if (away && !player.paused) {
    player.pause();
    autoPaused = true;
    touch();
  } else if (!away && autoPaused) {
    player.resume();
    autoPaused = false;
    touch();
  }
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden && !player.paused) {
    player.pause();
    autoPaused = true;
    touch();
  } else if (!document.hidden && autoPaused) {
    player.resume();
    autoPaused = false;
    touch();
  }
});

class RoomSystem extends createSystem() {
  private settle = 0;

  update(delta: number): void {
    if (recenter && world.visibilityState.value !== VisibilityState.NonImmersive) {
      // A few frames after entering, so the headset has reported a pose.
      if ((this.settle += 1) > 3) {
        const { head, yaw } = headPose();
        arrange(head, yaw);
        recenter = false;
        this.settle = 0;
      }
    } else if (recenter) {
      recenter = false;
    }
    // IWSDK passes seconds; a long frame (tab restored) is clamped.
    if (player.tick(Math.min(delta, 0.25) * 1000) > 0) dirty = true;
    if (!dirty) return;
    dirty = false;
    notice.style.display = 'none';
    for (const p of panels) p.update(player.state, player.paused);
  }
}
world.registerSystem(RoomSystem);

if (live) {
  player.ingest({ type: 'task_state', taskId: 'live', state: 'in_progress' });
  connectLive(
    live,
    'live',
    (event) => {
      player.ingest(event);
      touch();
    },
    (status) => {
      player.ingest({ type: 'status', role: 'System', agent: 'Room', message: status, taskId: 'live' });
      touch();
    },
  );
}

// Browser tests drive the emulator's hands against the real scene; `?e2e`
// lets them find the room. Nothing else reads it.
if (new URLSearchParams(location.search).has('e2e')) {
  (window as unknown as { __room: unknown }).__room = { world, player };
}
