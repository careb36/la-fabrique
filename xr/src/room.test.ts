import { describe, expect, it } from 'vitest';
import { REACH_M } from './layout';
import { findDesk, findWall, layoutRoom, type Surface } from './room';

const head = { x: 0, y: 1.2, z: 0 };

const desk = (over: Partial<Surface> = {}): Surface => ({
  kind: 'horizontal',
  label: 'table',
  center: { x: 0, y: 0.74, z: -0.55 },
  normal: { x: 0, y: 1, z: 0 },
  width: 1.2,
  depth: 0.6,
  ...over,
});

const wall = (over: Partial<Surface> = {}): Surface => ({
  kind: 'vertical',
  label: 'wall',
  center: { x: 0, y: 1.4, z: -1.6 },
  normal: { x: 0, y: 0, z: 1 },
  width: 3,
  depth: 2.5,
  ...over,
});

const floor: Surface = { ...desk(), label: 'floor', center: { x: 0, y: 0, z: -1 }, width: 4, depth: 4 };

const dist = (a: { x: number; y: number; z: number }) => Math.hypot(a.x - head.x, a.y - head.y, a.z - head.z);

describe('findDesk', () => {
  it('finds the table in front of a seated person', () => {
    expect(findDesk([floor, desk()], head)?.label).toBe('table');
  });

  it('never takes the floor or the ceiling for a desk', () => {
    expect(findDesk([floor], head)).toBeUndefined();
  });

  it('ignores a table out of reach', () => {
    expect(findDesk([desk({ center: { x: 0, y: 0.74, z: -2.2 } })], head)).toBeUndefined();
  });

  it('ignores a surface at the wrong height for a desk', () => {
    expect(findDesk([desk({ center: { x: 0, y: 1.15, z: -0.55 } })], head)).toBeUndefined();
  });
});

describe('findWall', () => {
  it('finds the wall ahead, facing the person', () => {
    expect(findWall([wall()], head, 0)?.label).toBe('wall');
  });

  it('ignores a wall behind, and doors and windows', () => {
    expect(findWall([wall({ center: { x: 0, y: 1.4, z: 1.6 }, normal: { x: 0, y: 0, z: -1 } })], head, 0)).toBeUndefined();
    expect(findWall([wall({ label: 'door' }), wall({ label: 'window' })], head, 0)).toBeUndefined();
  });

  it('does not trust the sign of the normal: the board faces the person either way', () => {
    const away = layoutRoom([wall({ normal: { x: 0, y: 0, z: -1 } })], head, 0, 3);
    expect(away.mode).toBe('wall');
    for (const p of away.agents) {
      expect(p.z).toBeCloseTo(-1.57, 2);
      expect(Math.cos(p.yaw)).toBeCloseTo(1);
    }
  });

  it('follows where the head looks', () => {
    const side = wall({ center: { x: -1.6, y: 1.4, z: 0 }, normal: { x: 1, y: 0, z: 0 } });
    expect(findWall([side], head, 0)).toBeUndefined();
    expect(findWall([side], head, Math.PI / 2)).toBeDefined();
  });
});

describe('layoutRoom', () => {
  it('stands the hand panels on the desk, within reach, leaning back', () => {
    const room = layoutRoom([floor, desk(), wall()], head, 0, 5);
    expect(room.mode).toBe('desk+wall');
    for (const p of room.hands) {
      expect(p.y).toBeCloseTo(0.745, 2);
      expect(p.anchor).toBe('bottom');
      expect(p.tilt).toBeGreaterThan(0);
      expect(dist(p)).toBeLessThanOrEqual(REACH_M + 1e-9);
    }
  });

  it('hangs the agents on the wall, larger, facing the room', () => {
    const room = layoutRoom([desk(), wall()], head, 0, 5);
    expect(room.agents).toHaveLength(5);
    for (const p of room.agents) {
      expect(p.z).toBeCloseTo(-1.57, 2);
      expect(p.scale).toBeGreaterThan(1);
      expect(p.yaw).toBeCloseTo(0);
    }
    const xs = room.agents.map((p) => p.x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
  });

  it('falls back to the floating arc in a room it cannot read', () => {
    const room = layoutRoom([], head, 0, 5);
    expect(room.mode).toBe('arc');
    expect(room.hands).toHaveLength(3);
    for (const p of room.hands) expect(dist(p)).toBeLessThanOrEqual(REACH_M);
  });

  it('uses whichever it finds: a wall without a desk', () => {
    const room = layoutRoom([wall()], head, 0, 5);
    expect(room.mode).toBe('wall');
    expect(room.hands[0].anchor).toBe('top');
  });
});
