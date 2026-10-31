/**
 * Where panels go around a seated person.
 *
 * Every panel sits on an arc in front of the head, at arm's length and a
 * little below eye level, so a hand reaches it without leaning or standing.
 * Positions are in meters relative to the head: x right, y up, -z forward.
 */

/** A seated person reaches comfortably to about 60 cm. */
export const REACH_M = 0.6;
/** Panels sit a little inside the reach so a poke does not need a full arm. */
export const PANEL_DISTANCE_M = 0.5;
/** Below eye level, where the forearm rests. */
export const PANEL_DROP_M = 0.15;

export interface Placement {
  x: number;
  y: number;
  z: number;
  /** Rotation around the vertical axis, so the panel faces the head. */
  yaw: number;
}

/**
 * Place `count` panels on an arc of `spreadDeg` degrees centered in front of
 * the head. One panel goes straight ahead.
 */
export function arc(
  count: number,
  spreadDeg = 100,
  distance = PANEL_DISTANCE_M,
  drop = PANEL_DROP_M,
): Placement[] {
  if (count <= 0) return [];
  const spread = (spreadDeg * Math.PI) / 180;
  const step = count === 1 ? 0 : spread / (count - 1);
  const start = count === 1 ? 0 : -spread / 2;
  return Array.from({ length: count }, (_, i) => {
    const angle = start + i * step;
    return {
      x: Math.sin(angle) * distance,
      y: -drop,
      z: -Math.cos(angle) * distance,
      yaw: -angle,
    };
  });
}

/** Distance from the head to a placement. */
export function reach(p: Placement): number {
  return Math.hypot(p.x, p.y, p.z);
}
