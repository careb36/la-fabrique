import { describe, expect, it } from 'vitest';
import { arc, around, reach, REACH_M } from './layout';

describe('arc', () => {
  it('puts a single panel straight ahead', () => {
    const [p] = arc(1);
    expect(p.x).toBeCloseTo(0);
    expect(p.z).toBeLessThan(0);
    expect(p.yaw).toBeCloseTo(0);
  });

  it('keeps every panel within a seated reach', () => {
    for (const count of [1, 2, 3, 5, 7]) {
      for (const p of arc(count, 140)) {
        expect(reach(p)).toBeLessThanOrEqual(REACH_M);
      }
    }
  });

  it('is symmetric and faces the head', () => {
    const [left, , right] = arc(3);
    expect(left.x).toBeCloseTo(-right.x);
    expect(left.yaw).toBeCloseTo(-right.yaw);
    expect(left.x).toBeLessThan(0);
  });

  it('places nothing for no panels', () => {
    expect(arc(0)).toEqual([]);
  });
});

describe('around', () => {
  const ahead = arc(1)[0];

  it('keeps a placement where it was for a head at the origin facing ahead', () => {
    const p = around(ahead, { x: 0, y: 0, z: 0 }, 0);
    expect(p.x).toBeCloseTo(ahead.x);
    expect(p.z).toBeCloseTo(ahead.z);
  });

  it('follows the head up and across: a standing person gets the room at their height', () => {
    const p = around(ahead, { x: 1, y: 1.6, z: 2 }, 0);
    expect(p.y).toBeCloseTo(1.6 + ahead.y);
    expect(p.x).toBeCloseTo(1);
    expect(p.z).toBeCloseTo(2 + ahead.z);
  });

  it('turns with the head: facing left puts the panel to the left', () => {
    const p = around(ahead, { x: 0, y: 0, z: 0 }, Math.PI / 2);
    expect(p.x).toBeCloseTo(ahead.z);
    expect(p.z).toBeCloseTo(0);
    expect(p.yaw).toBeCloseTo(Math.PI / 2);
  });

  it('keeps every panel within reach of the head it is placed around', () => {
    const head = { x: 0.3, y: 1.5, z: -0.2 };
    for (const at of arc(5, 140)) {
      const p = around(at, head, 0.7);
      expect(Math.hypot(p.x - head.x, p.y - head.y, p.z - head.z)).toBeLessThanOrEqual(REACH_M);
    }
  });
});
