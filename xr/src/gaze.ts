/**
 * Looking at an agent is enough to ask what it does: the head's direction
 * picks the panel it points at, and a short dwell opens it. Head direction,
 * not eye tracking, so it works on every headset and in the emulator.
 *
 * Pure geometry: positions and directions come in as plain numbers.
 */

import type { Vec3 } from './room';

/** Half-angle of the cone a target must be inside to count as looked at. */
export const GAZE_CONE_DEG = 9;
/** Seconds the head must stay on a target before it opens. */
export const GAZE_DWELL_S = 0.5;

/**
 * The index of the target closest to where `forward` points from `head`,
 * when it is inside the cone; -1 when the head looks at none of them.
 */
export function gazed(head: Vec3, forward: Vec3, targets: Vec3[], coneDeg = GAZE_CONE_DEG): number {
  const flen = Math.hypot(forward.x, forward.y, forward.z) || 1;
  const limit = Math.cos((coneDeg * Math.PI) / 180);
  let best = -1;
  let bestCos = limit;
  targets.forEach((t, i) => {
    const d = { x: t.x - head.x, y: t.y - head.y, z: t.z - head.z };
    const len = Math.hypot(d.x, d.y, d.z);
    if (len < 1e-6) return;
    const cos = (d.x * forward.x + d.y * forward.y + d.z * forward.z) / (len * flen);
    if (cos >= bestCos) {
      bestCos = cos;
      best = i;
    }
  });
  return best;
}

/**
 * Dwell: a target opens once the head has stayed on it `dwell` seconds, and
 * stays open until the head settles on another one or on nothing for as long.
 */
export class Dwell {
  open = -1;
  private candidate = -1;
  private held = 0;

  constructor(private readonly dwell = GAZE_DWELL_S) {}

  /** Feed the target looked at this frame; returns the open one. */
  update(target: number, dt: number): number {
    if (target === this.open) {
      this.candidate = target;
      this.held = 0;
      return this.open;
    }
    if (target !== this.candidate) {
      this.candidate = target;
      this.held = 0;
    }
    this.held += dt;
    if (this.held >= this.dwell) this.open = this.candidate;
    return this.open;
  }
}
