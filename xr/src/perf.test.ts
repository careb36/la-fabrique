import { describe, expect, it } from 'vitest';

import { FrameStats, perfLine } from './perf';

describe('FrameStats', () => {
  it('reports nothing until it has enough frames', () => {
    const s = new FrameStats();
    for (let i = 0; i < 5; i++) s.add(1 / 72);
    expect(s.report()).toBeUndefined();
  });

  it('measures a steady 72 Hz as 72 fps with no slow frames', () => {
    const s = new FrameStats(72);
    for (let i = 0; i < 200; i++) s.add(1 / 72);
    const r = s.report()!;
    expect(r.fps).toBeCloseTo(72, 5);
    expect(r.p95Ms).toBeCloseTo(1000 / 72, 5);
    expect(r.slow).toBe(0);
  });

  it('shows stutter in the 95th percentile and the share of slow frames', () => {
    const s = new FrameStats(72);
    for (let i = 0; i < 90; i++) s.add(1 / 72);
    for (let i = 0; i < 10; i++) s.add(1 / 30);
    const r = s.report()!;
    expect(r.p95Ms).toBeCloseTo(1000 / 30, 5);
    expect(r.slow).toBeCloseTo(0.1, 5);
  });

  it('ignores a resumed tab and nonsense', () => {
    const s = new FrameStats();
    for (let i = 0; i < 20; i++) s.add(1 / 72);
    s.add(5);
    s.add(0);
    s.add(Number.NaN);
    expect(s.report()!.slow).toBe(0);
  });

  it('writes one readable line', () => {
    expect(perfLine(undefined, 118, 48400)).toBe('Measuring... 118 draw calls, 48k triangles');
    const s = new FrameStats();
    for (let i = 0; i < 20; i++) s.add(1 / 72);
    expect(perfLine(s.report(), 90, 32000)).toBe('72 fps, p95 13.9 ms, 0% slow. 90 draw calls, 32k triangles');
  });
});
