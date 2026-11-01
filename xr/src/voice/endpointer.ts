/**
 * Where a phrase starts and ends, from a voice detector's verdict per window.
 *
 * Pure: windows of audio and a speech probability in, whole phrases out.
 * A phrase starts when the probability crosses `start`, keeps going while
 * it stays above `release` (a word that dips for a moment does not end
 * it), and ends after `silenceMs` below it. A little audio from before the
 * start (`prerollMs`) is kept, since the first consonant is often quiet; a
 * phrase shorter than `minSpeechMs` is a click, not a word; one longer than
 * `maxMs` is cut and handed over, so a monologue is still heard in pieces.
 */

export interface EndpointerOptions {
  sampleRate?: number;
  start?: number;
  release?: number;
  silenceMs?: number;
  prerollMs?: number;
  minSpeechMs?: number;
  maxMs?: number;
}

export class Endpointer {
  private readonly rate: number;
  private readonly start: number;
  private readonly release: number;
  private readonly silenceMs: number;
  private readonly prerollMs: number;
  private readonly minSpeechMs: number;
  private readonly maxMs: number;

  private preroll: Float32Array[] = [];
  private prerollSamples = 0;
  private phrase: Float32Array[] = [];
  private phraseSamples = 0;
  private speechSamples = 0;
  private silenceSamples = 0;
  private speaking = false;

  constructor(o: EndpointerOptions = {}) {
    this.rate = o.sampleRate ?? 16_000;
    this.start = o.start ?? 0.5;
    this.release = Math.min(o.release ?? 0.35, this.start);
    this.silenceMs = o.silenceMs ?? 600;
    this.prerollMs = o.prerollMs ?? 300;
    this.minSpeechMs = o.minSpeechMs ?? 250;
    this.maxMs = o.maxMs ?? 8_000;
  }

  get isSpeaking(): boolean {
    return this.speaking;
  }

  /** One window of audio with the detector's probability; a finished phrase, or nothing. */
  push(window: Float32Array, probability: number): Float32Array | undefined {
    if (!this.speaking) {
      if (probability >= this.start) {
        this.speaking = true;
        this.phrase = [...this.preroll];
        this.phraseSamples = this.prerollSamples;
        this.speechSamples = 0;
        this.silenceSamples = 0;
        this.preroll = [];
        this.prerollSamples = 0;
      } else {
        this.preroll.push(window);
        this.prerollSamples += window.length;
        const keep = (this.prerollMs / 1000) * this.rate;
        while (this.prerollSamples - (this.preroll[0]?.length ?? 0) >= keep && this.preroll.length > 1) {
          this.prerollSamples -= this.preroll.shift()!.length;
        }
        return undefined;
      }
    }
    this.phrase.push(window);
    this.phraseSamples += window.length;
    if (probability >= this.release) {
      this.speechSamples += window.length;
      this.silenceSamples = 0;
    } else {
      this.silenceSamples += window.length;
    }
    const silent = this.silenceSamples >= (this.silenceMs / 1000) * this.rate;
    const tooLong = this.phraseSamples >= (this.maxMs / 1000) * this.rate;
    if (!silent && !tooLong) return undefined;
    return this.finish();
  }

  /** The phrase in progress, if the microphone closes mid-sentence. */
  flush(): Float32Array | undefined {
    return this.speaking ? this.finish() : undefined;
  }

  reset(): void {
    this.preroll = [];
    this.prerollSamples = 0;
    this.phrase = [];
    this.phraseSamples = 0;
    this.speechSamples = 0;
    this.silenceSamples = 0;
    this.speaking = false;
  }

  private finish(): Float32Array | undefined {
    const enough = this.speechSamples >= (this.minSpeechMs / 1000) * this.rate;
    const out = enough ? concat(this.phrase, this.phraseSamples) : undefined;
    this.reset();
    return out;
  }
}

export function concat(parts: Float32Array[], total: number): Float32Array {
  const out = new Float32Array(total);
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

/** Silence before and after a phrase: a recognizer is unsure of a clip that starts mid-breath. */
export function padded(audio: Float32Array, seconds = 0.5, rate = 16_000): Float32Array {
  const pad = Math.round(seconds * rate);
  const out = new Float32Array(audio.length + 2 * pad);
  out.set(audio, pad);
  return out;
}
