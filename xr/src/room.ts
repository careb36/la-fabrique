/**
 * The real room decides where the factory goes.
 *
 * In passthrough the person's own desk and walls are part of the
 * experience: the panels a hand uses stand on the desk in front of them,
 * like papers on a work surface, and the agents hang on the wall ahead as
 * the team's board. Without a desk within reach or a wall ahead (or without
 * scene understanding at all) each falls back to the floating arc, so the
 * room works anywhere.
 *
 * Pure geometry: surfaces come in as plain numbers, placements come out.
 * World coordinates in meters, y up; a yaw of 0 looks down -z.
 */

import { arc, around, REACH_M, type Placement } from './layout';

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Surface {
  kind: 'horizontal' | 'vertical';
  /** The headset's label when it has one: 'table', 'desk', 'wall', 'floor'... */
  label: string;
  /** The surface's center, in world space. */
  center: Vec3;
  /**
   * Unit normal. Its sign is not trusted: headsets and emulators disagree on
   * whether a wall's normal points into the room, so it is turned toward the
   * person before use.
   */
  normal: Vec3;
  /** Extent along the surface, meters. */
  width: number;
  depth: number;
}

export interface Placed extends Placement {
  /** Tilt back from vertical, radians (0 stands upright). */
  tilt: number;
  /** Size relative to the panel's design size. */
  scale: number;
  /** Which edge the placement holds the panel by. */
  anchor: 'top' | 'bottom';
}

export interface RoomLayout {
  /** Where it went: on the desk, on the wall, both, or the floating arc. */
  mode: 'desk+wall' | 'desk' | 'wall' | 'arc';
  /** The three panels a hand uses: tasks, result, room controls. */
  hands: Placed[];
  /** The agents' panels. */
  agents: Placed[];
}

/** A desk is this far below the eyes of someone sitting at it. */
const DESK_BELOW_EYES = { min: 0.15, max: 0.85 };
/** Panels lean back a little on a desk, toward the eyes. */
const DESK_TILT = (18 * Math.PI) / 180;
/** The agents on a wall are read from further away, so they are larger. */
const WALL_SCALE = 1.8;
const WALL_RANGE = { min: 0.6, max: 3.5 };

const flat = (a: Vec3, b: Vec3) => Math.hypot(a.x - b.x, a.z - b.z);
const yawTowards = (from: Vec3, to: Vec3) => Math.atan2(-(to.x - from.x), -(to.z - from.z));
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));

/**
 * The desk in front of a seated head: a horizontal surface labeled as a
 * table or desk (or unlabeled, but never a floor or ceiling) at desk height
 * below the eyes, whose near edge a hand can reach. The nearest one wins.
 */
export function findDesk(surfaces: Surface[], head: Vec3): Surface | undefined {
  return surfaces
    .filter((s) => s.kind === 'horizontal')
    .filter((s) => !/floor|ceiling/i.test(s.label))
    .filter((s) => {
      const below = head.y - s.center.y;
      return below >= DESK_BELOW_EYES.min && below <= DESK_BELOW_EYES.max;
    })
    .filter((s) => nearEdge(s, head) <= deskReach(s, head))
    .sort((a, b) => nearEdge(a, head) - nearEdge(b, head))[0];
}

/** Horizontal distance from the head to the desk's nearest edge. */
function nearEdge(s: Surface, head: Vec3): number {
  return Math.max(0, flat(s.center, head) - Math.min(s.width, s.depth) / 2);
}

/** How far across a desk a hand reaches, given how far below the eyes it is. */
function deskReach(s: Surface, head: Vec3): number {
  const below = head.y - s.center.y;
  return Math.sqrt(Math.max(0, REACH_M * REACH_M - below * below));
}

/**
 * The wall ahead: a vertical surface facing the head, within reading range,
 * no more than 50 degrees off where the head looks. The nearest one wins.
 */
export function findWall(surfaces: Surface[], head: Vec3, yaw: number): Surface | undefined {
  return surfaces
    .filter((s) => s.kind === 'vertical' && !/door|window|art|screen/i.test(s.label))
    .filter((s) => {
      const d = flat(s.center, head);
      if (d < WALL_RANGE.min || d > WALL_RANGE.max) return false;
      return Math.abs(wrap(yawTowards(head, s.center) - yaw)) <= (50 * Math.PI) / 180;
    })
    .sort((a, b) => flat(a.center, head) - flat(b.center, head))[0];
}

/** A wall's horizontal normal, turned to point toward the head. */
function towardHead(s: Surface, head: Vec3): { x: number; z: number } {
  const len = Math.hypot(s.normal.x, s.normal.z) || 1;
  let n = { x: s.normal.x / len, z: s.normal.z / len };
  if (n.x * (head.x - s.center.x) + n.z * (head.z - s.center.z) < 0) n = { x: -n.x, z: -n.z };
  return n;
}

/** Where everything goes for a head at `head` looking `yaw`, in this room. */
export function layoutRoom(surfaces: Surface[], head: Vec3, yaw: number, agentCount: number): RoomLayout {
  const desk = findDesk(surfaces, head);
  const wall = findWall(surfaces, head, yaw);

  const floating = (p: Placement): Placed => ({ ...around(p, head, yaw), tilt: 0, scale: 1, anchor: 'top' });
  let hands = arc(3, 96, 0.45, 0.04).map(floating);
  let agents = arc(agentCount, 100, 0.55, 0).map((p) => ({ ...floating(p), anchor: 'bottom' as const }));

  if (desk) {
    // Stand the panels along the desk's near edge, a few centimeters in,
    // facing the head, leaning back toward the eyes.
    const toward = yawTowards(head, desk.center);
    // A few cm onto the desk, but far enough out that the three panels sit
    // side by side on their arc, and never past what a hand reaches.
    const reachAcross = Math.min(Math.max(nearEdge(desk, head) + 0.08, 0.38), deskReach(desk, head));
    hands = arc(3, 120, reachAcross, 0).map((p) => {
      const at = around(p, { ...head, y: desk.center.y }, toward);
      return { ...at, y: desk.center.y + 0.005, tilt: DESK_TILT, scale: 1, anchor: 'bottom' };
    });
  }
  if (wall) {
    // The team board: the agents side by side on the wall, centered on
    // where the head looks, a little above the eyes, a few cm off the wall.
    const spacing = 0.2 * WALL_SCALE + 0.04;
    const n = towardHead(wall, head);
    const facing = Math.atan2(n.x, n.z);
    const right = { x: Math.cos(facing), z: -Math.sin(facing) };
    const y = Math.max(head.y + 0.1, wall.center.y - 0.3);
    agents = Array.from({ length: agentCount }, (_, i) => {
      const offset = (i - (agentCount - 1) / 2) * spacing;
      return {
        x: wall.center.x + n.x * 0.03 + right.x * offset,
        y,
        z: wall.center.z + n.z * 0.03 + right.z * offset,
        yaw: facing,
        tilt: 0,
        scale: WALL_SCALE,
        anchor: 'bottom' as const,
      };
    });
  }
  const mode = desk && wall ? 'desk+wall' : desk ? 'desk' : wall ? 'wall' : 'arc';
  return { mode, hands, agents };
}
