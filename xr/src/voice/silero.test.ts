import { describe, expect, it } from 'vitest';

import { SileroVad, VAD_CONTEXT, VAD_WINDOW, type SessionLike, type TensorLike } from './silero';

/** A stand-in model: loud windows are speech, and the state counts the calls. */
function fakeSession() {
  const calls: { input: Float32Array; h: Float32Array }[] = [];
  const session: SessionLike = {
    async run(feeds) {
      const input = feeds.input.data as Float32Array;
      const h = feeds.h.data as Float32Array;
      calls.push({ input, h });
      const window = input.subarray(VAD_CONTEXT);
      let energy = 0;
      for (const x of window) energy += x * x;
      const probability = energy / window.length > 0.01 ? 0.95 : 0.02;
      const hn = Float32Array.from(h);
      hn[0] += 1;
      return { speech_probs: { data: new Float32Array([probability]) }, hn: { data: hn }, cn: { data: new Float32Array(128) } };
    },
  };
  const tensor = (data: Float32Array): TensorLike => ({ data });
  return { session, tensor, calls };
}

describe('SileroVad', () => {
  it('feeds the model whole windows with the samples before them, and carries its state', async () => {
    const { session, tensor, calls } = fakeSession();
    const vad = new SileroVad(session, tensor);
    const loud = new Float32Array(VAD_WINDOW * 2 + 100).fill(0.5);
    const out = await vad.feed(loud);
    expect(out).toHaveLength(2);
    for (const o of out) expect(o.probability).toBeCloseTo(0.95, 5);
    expect(calls[0].input).toHaveLength(VAD_CONTEXT + VAD_WINDOW);
    // The first window has silence before it; the second has the end of the first.
    expect(calls[0].input[0]).toBe(0);
    expect(calls[1].input[0]).toBe(0.5);
    // The state returned by one call is fed to the next.
    expect(calls[0].h[0]).toBe(0);
    expect(calls[1].h[0]).toBe(1);
    // The 100 leftover samples wait for the next call and lead its window.
    const more = await vad.feed(new Float32Array(VAD_WINDOW - 100).fill(0));
    expect(more).toHaveLength(1);
    expect(more[0].window[0]).toBe(0.5);
    expect(more[0].window[99]).toBe(0.5);
    expect(more[0].window[100]).toBe(0);
    expect(calls).toHaveLength(3);
  });

  it('reset forgets the state and the leftovers', async () => {
    const { session, tensor, calls } = fakeSession();
    const vad = new SileroVad(session, tensor);
    await vad.feed(new Float32Array(VAD_WINDOW + 10).fill(0.5));
    vad.reset();
    await vad.feed(new Float32Array(VAD_WINDOW).fill(0.5));
    expect(calls[1].h[0]).toBe(0);
    expect(calls[1].input[0]).toBe(0);
  });
});
