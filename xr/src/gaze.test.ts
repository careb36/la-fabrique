import { describe, expect, it } from 'vitest';

import { Dwell, gazed, GAZE_DWELL_S } from './gaze';

const head = { x: 0, y: 1.2, z: 0 };
const ahead = { x: 0, y: 0, z: -1 };
// Five panels on a wall 1.5 m ahead, 40 cm apart.
const wall = [-0.8, -0.4, 0, 0.4, 0.8].map((x) => ({ x, y: 1.3, z: -1.5 }));

describe('gazed', () => {
  it('picks the panel the head points at', () => {
    expect(gazed(head, ahead, wall)).toBe(2);
    const right = { x: 0.4, y: 0.1, z: -1.5 };
    expect(gazed(head, right, wall)).toBe(3);
  });

  it('picks none when the head looks away', () => {
    expect(gazed(head, { x: 0, y: -1, z: 0 }, wall)).toBe(-1);
    expect(gazed(head, { x: 1, y: 0, z: 0 }, wall)).toBe(-1);
  });

  it('ignores a target at the head itself', () => {
    expect(gazed(head, ahead, [head])).toBe(-1);
  });
});

describe('Dwell', () => {
  it('opens a target only after the head stays on it', () => {
    const d = new Dwell();
    expect(d.update(1, GAZE_DWELL_S / 2)).toBe(-1);
    expect(d.update(1, GAZE_DWELL_S / 2)).toBe(1);
  });

  it('keeps the open target through a glance elsewhere', () => {
    const d = new Dwell();
    d.update(1, GAZE_DWELL_S);
    expect(d.update(3, 0.1)).toBe(1);
    expect(d.update(1, 0.1)).toBe(1);
    expect(d.update(-1, GAZE_DWELL_S)).toBe(-1);
  });

  it('a glance never opens anything', () => {
    const d = new Dwell();
    for (const t of [0, 1, 2, 3, 4]) expect(d.update(t, 0.1)).toBe(-1);
  });
});
