/**
 * Director mode (`?director`): plays the demo video's script by itself in
 * the Quest 3 emulator, so it can be recorded without a headset. It moves
 * the emulated head and right hand the way a person would and lets the
 * room's real interactions do the rest: the pinch presses Launch, the grab
 * carries the delivery onto a ring, the head's dwell opens an agent. Nothing
 * is faked in the room's state.
 *
 * It needs the emulator (`window.IWER_DEVICE`), so on a real headset the
 * parameter does nothing. A caption says on screen where it was recorded,
 * and a badge marks the stretch played faster.
 */

import { Matrix4, Quaternion, Vector3, type Object3D } from 'three';

import { awaitingDecision, tokenAt, type Role } from './model';
import type { Player } from './engine/player';

/** What the director needs from the room. */
export interface Stage {
  player: Player;
  camera: Object3D;
  /** True once the person has clicked Enter XR. */
  inXR: () => boolean;
  token: () => Vector3;
  zone: (kind: 'approve' | 'reject') => Vector3;
  launchButton: () => Object3D | undefined;
  /** The first visible text with this label (a button's caption). */
  label: (text: string) => Object3D | undefined;
  agent: (role: Role) => Vector3;
  wall: () => Vector3;
  desk: () => Vector3;
  restart: () => void;
  newCompany: () => void;
  /** How many times faster than real time the demo's clock runs. */
  setSpeed: (times: number) => void;
  /** Voice is on and its recognizer is ready to hear (a model may load first). */
  voiceReady: () => boolean;
}

interface EmulatedHand {
  position: { set(x: number, y: number, z: number): void };
  quaternion: { set(x: number, y: number, z: number, w: number): void };
  updatePinchValue(v: number): void;
}

interface EmulatedDevice {
  controlMode: string;
  primaryInputMode: string;
  quaternion: { set(x: number, y: number, z: number, w: number): void };
  hands: { right: EmulatedHand; left: EmulatedHand };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Run `step(t)` with t going 0..1 (eased) over `ms` of wall-clock time,
 * whatever the frame rate: a slow machine takes fewer steps, not longer.
 */
async function over(ms: number, step: (t: number) => void): Promise<void> {
  const start = performance.now();
  for (;;) {
    const raw = Math.min(1, (performance.now() - start) / Math.max(1, ms));
    step(raw * raw * (3 - 2 * raw));
    if (raw >= 1) return;
    await sleep(16);
  }
}
const UP = new Vector3(0, 1, 0);

/** A DOM line over the page, for the recording. */
function overlay(text: string, corner: 'bottom-left' | 'top-right'): HTMLDivElement {
  const el = document.createElement('div');
  el.textContent = text;
  Object.assign(el.style, {
    position: 'fixed',
    zIndex: '10000',
    padding: '6px 12px',
    borderRadius: '8px',
    background: 'rgba(17,19,23,0.78)',
    color: '#f4f4f5',
    font: '600 15px/1.3 Inter, system-ui, sans-serif',
    pointerEvents: 'none',
    ...(corner === 'bottom-left' ? { left: '16px', bottom: '16px' } : { right: '16px', top: '64px' }),
  });
  document.body.append(el);
  return el;
}

export async function direct(stage: Stage): Promise<void> {
  const device = (window as unknown as { IWER_DEVICE?: EmulatedDevice }).IWER_DEVICE;
  if (!device) return; // a real headset: the person is the director

  overlay('Recorded in the Quest 3 emulator', 'bottom-left');
  const badge = overlay('', 'top-right');
  badge.style.display = 'none';
  const hint = overlay('Director mode: click Enter XR, then start recording.', 'top-right');
  while (!stage.inXR()) await sleep(200);
  hint.remove();
  await sleep(1500);

  device.controlMode = 'programmatic';
  device.primaryInputMode = 'hand';
  const hand = device.hands.right;
  const { player } = stage;

  // ---- the moves -------------------------------------------------------

  const headAt = () => stage.camera.getWorldPosition(new Vector3());
  const look = new Quaternion();
  const aim = (from: Vector3, to: Vector3) => look.setFromRotationMatrix(new Matrix4().lookAt(from, to, UP));

  let headQ = stage.camera.getWorldQuaternion(new Quaternion());
  /** Turn the head toward a point, smoothly, over `ms`. */
  async function lookAt(target: Vector3, ms = 900): Promise<void> {
    const from = headQ.clone();
    const to = aim(headAt(), target).clone();
    await over(ms, (t) => {
      const q = from.clone().slerp(to, t);
      device!.quaternion.set(q.x, q.y, q.z, q.w);
    });
    headQ = to;
  }

  /** Where the right hand rests: low and to the right of the head. */
  const rest = () => headAt().add(new Vector3(0.14, -0.32, -0.12));
  let handAt = rest();
  /** Move the hand to `to`, pointing at `target`, over `ms`. */
  async function reach(to: Vector3, target: Vector3, ms = 700): Promise<void> {
    const from = handAt.clone();
    await over(ms, (t) => {
      const at = from.clone().lerp(to, t);
      hand.position.set(at.x, at.y, at.z);
      const q = aim(at, target);
      hand.quaternion.set(q.x, q.y, q.z, q.w);
    });
    handAt = to.clone();
  }

  /** Point at a button from the resting hand and pinch it. */
  async function press(button: Object3D | undefined): Promise<void> {
    if (!button) return;
    const at = button.getWorldPosition(new Vector3());
    await reach(rest(), at, 600);
    await sleep(300);
    hand.updatePinchValue(1);
    await sleep(250);
    hand.updatePinchValue(0);
    await sleep(400);
  }

  /**
   * Pinch the delivery, carry it onto a ring, let go. It waits until the
   * delivery rests above the result panel (another task's agent may still
   * hold the work), and tries again if a release missed.
   */
  async function carry(kind: 'approve' | 'reject'): Promise<void> {
    for (let attempt = 0; attempt < 3; attempt++) {
      const waiting = awaitingDecision(player.state);
      if (!waiting) return;
      const end = performance.now() + 60_000;
      while (tokenAt(player.state) !== 'result' && performance.now() < end) await sleep(100);
      await sleep(1500); // the delivery glides down
      await carryOnce(kind);
      if (player.state.tasks[waiting.id].state !== 'waiting_for_person') return;
    }
  }

  async function carryOnce(kind: 'approve' | 'reject'): Promise<void> {
    const token = stage.token();
    await lookAt(token.clone().add(new Vector3(0, -0.05, 0)), 700);
    const start = rest();
    await reach(start, token, 600);
    await sleep(300);
    hand.updatePinchValue(1);
    await sleep(400);
    // The delivery moves with the hand: move the hand by the way to the ring.
    const way = stage.zone(kind).sub(token);
    await reach(start.clone().add(way), stage.zone(kind), 1400);
    await sleep(600);
    hand.updatePinchValue(0);
    await sleep(600);
    await reach(rest(), stage.wall(), 500);
  }

  /** Wait until a task waits for the person (or `ms` passes). */
  async function waitFor(taskId: string, state: string, ms = 120_000): Promise<void> {
    const end = performance.now() + ms;
    while (player.state.tasks[taskId]?.state !== state && performance.now() < end) await sleep(100);
    await sleep(1500); // let the delivery glide into place
  }

  /** Run the demo's clock faster, with the badge on screen. */
  function speed(times: number): void {
    stage.setSpeed(times);
    badge.textContent = `${times}× speed`;
    badge.style.display = times === 1 ? 'none' : 'block';
  }

  // ---- the script (see the video script in the Devpost draft) ---------

  // A fresh company, so the learning curve starts empty.
  stage.newCompany();
  await sleep(800);

  // 0:00 Cold open: a delivery waits; carried onto Approve.
  speed(8);
  player.launch('reset');
  await lookAt(stage.desk(), 10);
  await waitFor('reset', 'waiting_for_person');
  speed(1);
  await carry('approve');
  await sleep(1500);

  // 0:12 The room: the desk, the wall with the team, back to the desk.
  await lookAt(stage.wall(), 2200);
  await sleep(2500);
  await lookAt(stage.agent('Architect'), 1800);
  await lookAt(stage.agent('ScrumMaster'), 2600);
  await lookAt(stage.desk(), 2000);
  await sleep(1500);

  // 0:30 Start over; the guide points at Launch; pinch it.
  stage.restart();
  await sleep(2500);
  await lookAt(stage.launchButton()?.getWorldPosition(new Vector3()) ?? stage.desk(), 900);
  await sleep(1500);
  await press(stage.launchButton());

  // 0:45 The work travels; the Verifier's seals. Watch the wall.
  await lookAt(stage.wall(), 1200);
  while (player.state.agents.Verifier.state !== 'working') await sleep(100);
  // 1:15 Rest the head on the Verifier: its panel opens.
  await lookAt(stage.agent('Verifier').add(new Vector3(0, -0.12, 0)), 900);
  await sleep(3500);
  await lookAt(stage.wall(), 900);

  // 1:30 It waits for the person: send it back; the rework.
  await waitFor('reset', 'waiting_for_person');
  await carry('reject');
  await lookAt(stage.wall(), 900);
  // 1:55 It comes back: approve.
  await waitFor('reset', 'waiting_for_person');
  await carry('approve');
  await sleep(1500);

  // 2:05 The rest of the sprint, faster: QA closes the CSV, the CI waits.
  speed(4);
  player.launch('csv');
  player.launch('ci');
  await waitFor('ci', 'waiting_for_person');
  speed(1);
  await carry('approve');
  while (player.state.tasks.csv.state !== 'done') await sleep(100);
  // The sprint closes; the curve gets its first bar.
  await sleep(1500);
  await lookAt(stage.agent('ScrumMaster'), 1200);
  await sleep(4000);

  // 2:20 Next sprint, with the procedures: no rework this time.
  await lookAt(stage.desk(), 900);
  await press(stage.label('Next sprint'));
  speed(4);
  for (const id of ['reset', 'csv', 'ci']) player.launch(id);
  await lookAt(stage.wall(), 900);
  // Approve whatever waits, in the order it comes, until the sprint closes.
  while (Object.values(player.state.tasks).some((t) => t.state !== 'done')) {
    if (awaitingDecision(player.state)) {
      speed(1);
      await carry('approve');
      speed(4);
    }
    await sleep(200);
  }
  speed(1);
  await sleep(1500);
  await lookAt(stage.agent('ScrumMaster'), 1200);
  await sleep(4500);

  // 2:40 Another way in: high contrast.
  await lookAt(stage.desk(), 900);
  await press(stage.label('Contrast'));
  await sleep(3000);
  await press(stage.label('Contrast off'));
  await sleep(1500);

  // 2:50 Another way in: voice. The director presses Voice and asks the
  // person recording to speak; the room's real recognizer does the rest.
  // Without a microphone (a headless run) nothing happens and it moves on.
  const voiceButton = stage.label('Voice');
  if (voiceButton) {
    await press(voiceButton);
    // The first time, the recognizer downloads its model: the Room panel
    // shows the progress; the request to speak waits until it can hear.
    const prompt = overlay('Voice is getting ready...', 'top-right');
    await until(stage.voiceReady, 120_000);
    prompt.textContent = 'Say: "pará un momento" or "pause"';
    const paused = await until(() => player.paused, 20_000);
    if (paused) {
      await sleep(2500);
      prompt.textContent = 'Say: "continuá" or "resume"';
      await until(() => !player.paused, 15_000);
      await sleep(2000);
    } else {
      prompt.textContent = 'No microphone here: voice skipped.';
      await sleep(2000);
    }
    prompt.remove();
    await press(stage.label('Voice'));
    await sleep(800);
  }

  await lookAt(stage.wall(), 1500);
  overlay('The end. Stop recording.', 'top-right');
}

/** True as soon as `check` holds, false once `ms` have passed without it. */
async function until(check: () => boolean, ms: number): Promise<boolean> {
  const end = performance.now() + ms;
  while (performance.now() < end) {
    if (check()) return true;
    await sleep(100);
  }
  return check();
}
