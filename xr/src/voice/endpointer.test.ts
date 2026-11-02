import { describe, expect, it } from 'vitest';

import { concat, Endpointer, padded } from './endpointer';

const RATE = 16_000;
const WINDOW = 512;
let counter = 0;
/** A window whose samples carry a serial number, so the output can be read back. */
function window(): Float32Array {
  return new Float32Array(WINDOW).fill(++counter);
}
function windowsFor(ms: number): number {
  return Math.ceil(((ms / 1000) * RATE) / WINDOW);
}

describe('Endpointer', () => {
  it('hands over a phrase after speech followed by silence, with a little audio from before', () => {
    counter = 0;
    const e = new Endpointer({ silenceMs: 600, prerollMs: 300, minSpeechMs: 250 });
    const quietBefore = Array.from({ length: 20 }, () => e.push(window(), 0.05));
    expect(quietBefore.every((x) => x === undefined)).toBe(true);
    for (let i = 0; i < windowsFor(500); i++) expect(e.push(window(), 0.9)).toBeUndefined();
    expect(e.isSpeaking).toBe(true);
    let out: Float32Array | undefined;
    for (let i = 0; i < windowsFor(600) + 1 && !out; i++) out = e.push(window(), 0.05);
    expect(out).toBeDefined();
    // The preroll keeps about 300 ms: the last ~10 of the 20 quiet windows.
    const firstSerial = out![0];
    expect(firstSerial).toBeGreaterThan(8);
    expect(firstSerial).toBeLessThanOrEqual(12);
    expect(e.isSpeaking).toBe(false);
  });

  it('ignores a click: speech shorter than the minimum', () => {
    const e = new Endpointer({ minSpeechMs: 250, silenceMs: 300 });
    for (let i = 0; i < 2; i++) e.push(window(), 0.9);
    let out: Float32Array | undefined;
    for (let i = 0; i < windowsFor(300) + 1; i++) out = e.push(window(), 0.0) ?? out;
    expect(out).toBeUndefined();
  });

  it('a dip below the start threshold but above the release does not end the phrase', () => {
    const e = new Endpointer({ start: 0.5, release: 0.35, silenceMs: 300 });
    e.push(window(), 0.9);
    for (let i = 0; i < windowsFor(400); i++) expect(e.push(window(), 0.4)).toBeUndefined();
    expect(e.isSpeaking).toBe(true);
  });

  it('cuts a phrase that runs too long', () => {
    const e = new Endpointer({ maxMs: 1000 });
    let out: Float32Array | undefined;
    let n = 0;
    while (!out && n < 100) {
      out = e.push(window(), 0.9);
      n++;
    }
    expect(out).toBeDefined();
    expect(n).toBe(windowsFor(1000));
    expect(e.isSpeaking).toBe(false);
  });

  it('flush hands over what was being said; nothing when quiet', () => {
    const e = new Endpointer({ minSpeechMs: 100 });
    expect(e.flush()).toBeUndefined();
    for (let i = 0; i < windowsFor(200); i++) e.push(window(), 0.9);
    expect(e.flush()).toBeDefined();
    expect(e.isSpeaking).toBe(false);
  });
});

describe('audio helpers', () => {
  it('concat joins parts in order', () => {
    expect(Array.from(concat([new Float32Array([1, 2]), new Float32Array([3])], 3))).toEqual([1, 2, 3]);
  });

  it('padded adds silence on both sides', () => {
    const out = padded(new Float32Array([1, 1]), 0.5, 4);
    expect(Array.from(out)).toEqual([0, 0, 1, 1, 0, 0]);
  });
});
