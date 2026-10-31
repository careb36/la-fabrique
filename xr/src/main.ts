import { createSystem, Interactable, SessionMode, UIKitDocument, VisibilityState, World } from '@iwsdk/core';

import { DEMO_TASKS } from './demo/scenario';
import { Player } from './engine/player';
import { arc, type Placement } from './layout';
import { ROLES } from './model';
import { agentPanel, controlPanel, resultPanel, taskPanel, type Panel } from './ui/panels';

/** Seated eye height above the floor. */
const HEAD_Y = 1.2;

const container = document.getElementById('scene-container') as HTMLDivElement;

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
});

const player = new Player(DEMO_TASKS);
/** Paused by the headset (system menu, headset off), not by the person. */
let autoPaused = false;

const panels: Panel[] = [];
let dirty = true;
const touch = () => {
  dirty = true;
};

function place(p: Panel, at: Placement): void {
  const entity = world.createTransformEntity().addComponent(Interactable);
  entity.object3D!.add(new UIKitDocument(p.root));
  entity.object3D!.position.set(at.x, HEAD_Y + at.y, at.z);
  entity.object3D!.rotation.y = at.yaw;
  panels.push(p);
}

// Everything a hand touches hangs from one arc at 45 cm, just below eye
// level: tasks on the left, the result ahead, the room's controls on the right.
const [left, center, right] = arc(3, 96, 0.45, 0.04);
place(
  taskPanel(DEMO_TASKS, (id) => {
    if (player.launch(id)) touch();
  }),
  left,
);
place(
  resultPanel((id, approved) => {
    if (player.decide(id, approved, approved ? '' : 'add a test for a reused token')) touch();
  }),
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
    onRestart: () => {
      player.restart();
      touch();
    },
  }),
  right,
);
// The agents only show, so they stand on a slightly farther arc just above it.
arc(ROLES.length, 100, 0.55, 0).forEach((at, i) => place(agentPanel({ ...player.state.agents[ROLES[i]] }), at));

// Leaving the headset or opening the system menu pauses the room; coming
// back resumes it, unless the person had paused it themselves.
world.visibilityState.subscribe((v) => {
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
  update(delta: number): void {
    // IWSDK passes seconds; a long frame (tab restored) is clamped.
    if (player.tick(Math.min(delta, 0.25) * 1000) > 0) dirty = true;
    if (!dirty) return;
    dirty = false;
    for (const p of panels) p.update(player.state, player.paused);
  }
}
world.registerSystem(RoomSystem);
