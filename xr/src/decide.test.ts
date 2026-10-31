import { describe, expect, it } from 'vitest';

import { DROP_RADIUS_M, dropOn } from './decide';

const approve = { x: 0.15, y: 1, z: -0.4 };
const reject = { x: -0.15, y: 1, z: -0.4 };

describe('dropOn', () => {
  it('lands on the zone it is released over', () => {
    expect(dropOn({ x: 0.16, y: 1.02, z: -0.41 }, approve, reject)).toBe('approve');
    expect(dropOn({ x: -0.14, y: 0.98, z: -0.38 }, approve, reject)).toBe('reject');
  });

  it('lands nowhere when released away from both', () => {
    expect(dropOn({ x: 0, y: 1, z: -0.4 }, approve, reject)).toBeUndefined();
    expect(dropOn({ x: 0.15, y: 1 + DROP_RADIUS_M + 0.01, z: -0.4 }, approve, reject)).toBeUndefined();
  });

  it('picks the nearer zone when both are within reach', () => {
    const close = { x: 0.02, y: 1, z: -0.4 };
    expect(dropOn(close, approve, reject, 0.5)).toBe('approve');
    expect(dropOn({ ...close, x: -0.02 }, approve, reject, 0.5)).toBe('reject');
  });
});
