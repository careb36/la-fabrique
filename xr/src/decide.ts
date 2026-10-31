/**
 * Deciding with the hands: the person takes the delivery and drops it on
 * Approve or Send back. Which one it landed on is plain geometry.
 */

import type { Vec3 } from './room';

export type Drop = 'approve' | 'reject';

/** How close to a zone's center a release counts as a drop on it, meters. */
export const DROP_RADIUS_M = 0.09;

const dist = (a: Vec3, b: Vec3) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

/**
 * The zone a release at `at` lands on: the nearer of the two when within
 * `radius` of it, otherwise none (the delivery goes back where it was).
 */
export function dropOn(at: Vec3, approve: Vec3, reject: Vec3, radius = DROP_RADIUS_M): Drop | undefined {
  const a = dist(at, approve);
  const r = dist(at, reject);
  if (Math.min(a, r) > radius) return undefined;
  return a <= r ? 'approve' : 'reject';
}
