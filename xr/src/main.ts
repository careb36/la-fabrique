import {
  createSystem,
  DistanceGrabbable,
  Grabbed,
  MovementMode,
  PokeInteractable,
  RayInteractable,
  SessionMode,
  UIKitDocument,
  VisibilityState,
  World,
} from '@iwsdk/core';
import { Object3D, Vector3 } from 'three';

import { dropOn } from './decide';
import { DEMO_TASKS } from './demo/scenario';
import { Player } from './engine/player';
import { layoutRoom, type Placed, type RoomLayout, type Surface } from './room';
import { SurfaceSystem } from './surfaces';
import { connectLive, liveConfig } from './live';
import { awaitingDecision, ROLES, tokenAt } from './model';
import { agentPanel, controlPanel, resultPanel, taskPanel, type Panel } from './ui/panels';
import { dropZone, presence, token } from './ui/presence';

/** Seated eye height above the floor. */
const HEAD_Y = 1.2;
/** Seconds after entering XR (or Recenter) before reading the room. */
const SURFACE_WAIT_S = 1.2;

const PLACEMENT_TEXT: Record<RoomLayout['mode'], string> = {
  'desk+wall': 'On your desk, the team on your wall.',
  desk: 'On your desk.',
  wall: 'The team on your wall.',
  arc: 'Floating in front of you.',
};

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
    // The room's table and walls (plane and mesh detection) and an anchor
    // that keeps the factory where it was put; optional, so a browser
    // without them still opens the room.
    features: { handTracking: true, planeDetection: true, meshDetection: true, anchors: true },
  },
  // The desktop view only: a step back from the seat so every panel fits on
  // a screen. In a headset, tracking puts the camera at the person's eyes.
  render: { fov: 75, camera: { position: [0, HEAD_Y + 0.05, 0.42], lookAt: [0, HEAD_Y - 0.08, -0.45] } },
  // Grabbing: the person takes the delivery in hand to decide on it.
  features: { grabbing: true, locomotion: false, physics: false, sceneUnderstanding: true },
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

interface Hosted {
  object: Object3D;
  root: Panel['root'];
  /** The edge the panel is held by, from the last layout. */
  anchor?: 'top' | 'bottom';
}
const handPanels: Hosted[] = [];
const agentPanels: Hosted[] = [];

function place(p: Panel, group: Hosted[]): void {
  // Both ways a hand presses a button: a fingertip crossing it (poke) and a
  // pinch while pointing at it (ray). Either works with controllers too.
  const entity = world.createTransformEntity().addComponent(RayInteractable).addComponent(PokeInteractable);
  entity.object3D!.add(new UIKitDocument(p.root));
  group.push({ object: entity.object3D!, root: p.root });
  panels.push(p);
}

/** Where the panels are now: on the desk and wall, or the floating arc. */
let placement: RoomLayout['mode'] = 'arc';

function apply(group: Hosted[], spots: Placed[]): void {
  group.forEach(({ object, root }, i) => {
    const at = spots[i];
    object.position.set(at.x, at.y, at.z);
    // Turn to face the head first, then lean back.
    object.rotation.set(-at.tilt, at.yaw, 0, 'YXZ');
    object.scale.setScalar(at.scale);
    root.setProperties({ anchorY: at.anchor });
    group[i].anchor = at.anchor;
  });
}

/** Lay the room out around a head, on whatever surfaces the room has. */
function arrange(head: Vector3, yaw: number, found: Surface[] = []): void {
  const room = layoutRoom(found, head, yaw, agentPanels.length);
  apply(handPanels, room.hands);
  apply(agentPanels, room.agents);
  placement = room.mode;
  touch();
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

// Tasks on the left, the result ahead, the room's controls on the right:
// on the desk when there is one, otherwise on a floating arc.
place(
  taskPanel(
    tasks,
    (id) => {
      if (player.launch(id)) touch();
    },
    live ? 'Watching the factory: tasks start from the web app.' : undefined,
  ),
  handPanels,
);
place(
  resultPanel((id, approved) => decide(id, approved), live ? 'Live mode watches: approve or send back in the web app.' : undefined),
  handPanels,
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
    where: () => PLACEMENT_TEXT[placement],
  }),
  handPanels,
);
// The agents only show: on the wall ahead as the team's board, or above.
for (const role of ROLES) place(agentPanel({ ...player.state.agents[role] }), agentPanels);

// Each agent's light sits just above its panel, wherever the panel goes;
// the task travels between them and down to the result.
const presences = ROLES.map((role, i) => {
  const p = presence(role);
  p.group.position.set(0, 0.22, 0.01);
  agentPanels[i].object.add(p.group);
  return { role, p, state: player.state.agents[role].state, changedAt: 0 };
});
const task = token();
// The delivery can be taken in hand: a pinch while pointing at it, near or
// across the desk, moves it with the hand. Dropped on Approve or Send back
// it decides; anywhere else it glides back.
const taskEntity = world.createTransformEntity(task.group).addComponent(DistanceGrabbable, {
  movementMode: MovementMode.MoveAtSource,
  rotate: false,
  scale: false,
});
const target = new Vector3();
const DECISION = { decline: 'add a test for a reused token' };

/** Approve on the right, Send back on the left, beside the delivery. */
const zones = {
  approve: dropZone('Approve', 0xa3e635),
  reject: dropZone('Send back', 0xf87171),
};
handPanels[1].object.add(zones.approve.group, zones.reject.group);
let held = false;

function decide(id: string, approved: boolean): void {
  if (player.decide(id, approved, approved ? '' : DECISION.decline)) touch();
}

/** Where the task should be now, in world space, or undefined when idle. */
function taskTarget(): Vector3 | undefined {
  const at = tokenAt(player.state);
  if (at === 'none') return undefined;
  if (at === 'result') {
    // Just above the result panel's top edge.
    const { object, anchor } = handPanels[1];
    return object.localToWorld(target.set(0, anchor === 'bottom' ? 0.42 : 0.05, 0.02));
  }
  const holder = presences.find((x) => x.role === at)!;
  return holder.p.group.localToWorld(target.set(0, 0.05, 0));
}
arrange(SEATED_HEAD, 0);

// Leaving the headset or opening the system menu pauses the room; coming
// back resumes it, unless the person had paused it themselves.
world.visibilityState.subscribe((v) => {
  // Entering XR: the room moves to wherever the person's head is, sitting or
  // standing. Leaving it: back to the seated view of the desktop page.
  if (v === VisibilityState.Visible && previous === VisibilityState.NonImmersive) recenter = true;
  if (v === VisibilityState.NonImmersive && previous !== VisibilityState.NonImmersive) arrange(SEATED_HEAD, 0);
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

const surfaces = world.registerSystem(SurfaceSystem).getSystem(SurfaceSystem)!;

class RoomSystem extends createSystem() {
  private waited = 0;

  /** The drop zones and the delivery in hand: release over a zone decides. */
  hands(time: number): void {
    // Only a delivery that waits for a person can be decided, and in live
    // mode the web app decides.
    const waiting = live ? undefined : awaitingDecision(player.state);
    const { anchor } = handPanels[1];
    // Level with where the delivery rests above the result panel.
    const y = anchor === 'bottom' ? 0.42 : 0.05;
    zones.approve.group.position.set(0.17, y, 0.03);
    zones.reject.group.position.set(-0.17, y, 0.03);
    const at = task.group.getWorldPosition(new Vector3());
    const approveAt = zones.approve.group.getWorldPosition(new Vector3());
    const rejectAt = zones.reject.group.getWorldPosition(new Vector3());
    const over = held ? dropOn(at, approveAt, rejectAt) : undefined;
    zones.approve.update(!!waiting, over === 'approve', time);
    zones.reject.update(!!waiting, over === 'reject', time);
    const now = taskEntity.hasComponent(Grabbed);
    if (held && !now && waiting) {
      const landed = dropOn(at, approveAt, rejectAt);
      if (landed) decide(waiting.id, landed === 'approve');
    }
    held = now;
  }

  update(delta: number, time: number): void {
    if (recenter && world.visibilityState.value !== VisibilityState.NonImmersive) {
      // Give the headset a moment to report its pose and the room's
      // surfaces, then lay the factory out on them.
      if ((this.waited += delta) > SURFACE_WAIT_S) {
        const { head, yaw } = headPose();
        arrange(head, yaw, surfaces.room());
        recenter = false;
        this.waited = 0;
      }
    } else if (recenter) {
      recenter = false;
    }
    // IWSDK passes seconds; a long frame (tab restored) is clamped.
    if (player.tick(Math.min(delta, 0.25) * 1000) > 0) dirty = true;
    // The lights and the task move every frame; the panels only on a change.
    for (const x of presences) {
      const now = player.state.agents[x.role].state;
      if (now !== x.state) {
        x.state = now;
        x.changedAt = time;
      }
      x.p.update(now, time, x.changedAt);
    }
    this.hands(time);
    task.update(taskTarget(), player.state.seals, delta, time, held);
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
  (window as unknown as { __room: unknown }).__room = {
    world,
    player,
    placement: () => placement,
    surfaces: () => surfaces.room(),
    token: () => task.group.getWorldPosition(new Vector3()),
    zones: () => ({
      approve: zones.approve.group.getWorldPosition(new Vector3()),
      reject: zones.reject.group.getWorldPosition(new Vector3()),
    }),
    held: () => held,
  };
}
