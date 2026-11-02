/**
 * Silero VAD v6 in the browser: is there a voice in this window?
 *
 * The model reads 512 new samples (32 ms at 16 kHz) with the 64 before
 * them, and carries a state between windows, so it is fed in order. It is
 * decoupled from the ONNX runtime: the caller hands in a session and a
 * tensor constructor, so the same class runs on onnxruntime-web (through
 * transformers.js's copy of it) and in a test with a stand-in.
 */

export const VAD_SAMPLE_RATE = 16_000;
export const VAD_WINDOW = 512;
export const VAD_CONTEXT = 64;

export interface TensorLike {
  data: Float32Array | ArrayLike<number>;
}

export interface SessionLike {
  run(feeds: Record<string, TensorLike>): Promise<Record<string, TensorLike>>;
}

export type MakeTensor = (data: Float32Array, dims: number[]) => TensorLike;

export class SileroVad {
  private h: Float32Array = new Float32Array(128);
  private c: Float32Array = new Float32Array(128);
  private context: Float32Array = new Float32Array(VAD_CONTEXT);
  private pending: Float32Array = new Float32Array(0);

  constructor(
    private readonly session: SessionLike,
    private readonly tensor: MakeTensor,
  ) {}

  reset(): void {
    this.h = new Float32Array(128);
    this.c = new Float32Array(128);
    this.context = new Float32Array(VAD_CONTEXT);
    this.pending = new Float32Array(0);
  }

  /**
   * Feed any number of samples (float, 16 kHz); get back each full window
   * with its speech probability. Samples left over wait for the next call.
   */
  async feed(samples: Float32Array): Promise<{ window: Float32Array; probability: number }[]> {
    const joined = new Float32Array(this.pending.length + samples.length);
    joined.set(this.pending);
    joined.set(samples, this.pending.length);
    const out: { window: Float32Array; probability: number }[] = [];
    let at = 0;
    for (; at + VAD_WINDOW <= joined.length; at += VAD_WINDOW) {
      const window = joined.slice(at, at + VAD_WINDOW);
      out.push({ window, probability: await this.run(window) });
    }
    this.pending = joined.slice(at);
    return out;
  }

  private async run(window: Float32Array): Promise<number> {
    const input = new Float32Array(VAD_CONTEXT + VAD_WINDOW);
    input.set(this.context);
    input.set(window, VAD_CONTEXT);
    const result = await this.session.run({
      input: this.tensor(input, [1, VAD_CONTEXT + VAD_WINDOW]),
      h: this.tensor(this.h, [1, 1, 128]),
      c: this.tensor(this.c, [1, 1, 128]),
    });
    this.h = Float32Array.from(result.hn.data as ArrayLike<number>);
    this.c = Float32Array.from(result.cn.data as ArrayLike<number>);
    this.context = window.slice(VAD_WINDOW - VAD_CONTEXT);
    return Number((result.speech_probs.data as ArrayLike<number>)[0]);
  }
}
