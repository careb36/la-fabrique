import { describe, expect, it } from 'vitest';
import { arc, reach, REACH_M } from './layout';

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
