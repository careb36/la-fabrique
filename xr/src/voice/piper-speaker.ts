/**
 * The on-device speaker: Piper in a worker, a voice per language, played
 * through WebAudio. For a browser without `speechSynthesis` (the Meta
 * Quest's) and for anyone who prefers a voice that works offline.
 */

import type { Lang, Localized, Speaker } from './types';
import type { FromPiperWorker, ToPiperWorker } from './piper.worker';

/** Piper voices of the mirror the library reads; Rioplatense is not among them yet. */
export const PIPER_VOICES: Localized<string> = { es: 'es_MX-claude-high', en: 'en_US-hfc_female-medium' };

export type SpeakerStatus = { kind: 'loading'; percent: number; lang: Lang } | { kind: 'spoken'; lang: Lang; synthesisSeconds: number; audioSeconds: number };

export interface PiperSpeakerOptions {
  voices?: Partial<Localized<string>>;
  onStatus?: (status: SpeakerStatus) => void;
  createWorker?: () => Worker;
  /** Plays 16-bit PCM WAV bytes; resolves when done. The default uses WebAudio. */
  play?: (wav: ArrayBuffer) => Promise<number>;
}

export class PiperSpeaker implements Speaker {
  readonly name = 'piper';
  private worker: Worker | undefined;
  private nextId = 1;
  private readonly waiting = new Map<number, { resolve: (wav: { wav: ArrayBuffer; seconds: number }) => void; reject: (e: Error) => void; lang: Lang }>();
  private stopCurrent: (() => void) | undefined;
  private readonly voices: Localized<string>;
  private readonly play: (wav: ArrayBuffer) => Promise<number>;

  constructor(private readonly o: PiperSpeakerOptions = {}) {
    this.voices = { ...PIPER_VOICES, ...Object.fromEntries(Object.entries(o.voices ?? {}).filter(([, v]) => v)) } as Localized<string>;
    this.play = o.play ?? ((wav) => playWav(wav, (stop) => (this.stopCurrent = stop)));
  }

  available(): boolean {
    const canWork = !!this.o.createWorker || typeof Worker !== 'undefined';
    const canPlay = !!this.o.play || typeof (globalThis as { AudioContext?: unknown }).AudioContext === 'function';
    return canWork && canPlay && typeof WebAssembly !== 'undefined';
  }

  async say(text: string, lang: Lang): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed) return;
    const { wav, seconds } = await this.synthesize(trimmed, lang);
    const audioSeconds = await this.play(wav);
    this.o.onStatus?.({ kind: 'spoken', lang, synthesisSeconds: seconds, audioSeconds });
  }

  stop(): void {
    this.stopCurrent?.();
    this.stopCurrent = undefined;
  }

  private synthesize(text: string, lang: Lang): Promise<{ wav: ArrayBuffer; seconds: number }> {
    const worker = this.ensureWorker();
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.waiting.set(id, { resolve, reject, lang });
      const m: ToPiperWorker = { type: 'speak', id, text, voiceId: this.voices[lang] };
      worker.postMessage(m);
    });
  }

  private ensureWorker(): Worker {
    if (this.worker) return this.worker;
    const worker = (this.o.createWorker ?? defaultWorker)();
    worker.onmessage = (e: MessageEvent<FromPiperWorker>) => {
      const m = e.data;
      if (m.type === 'progress') {
        const lang = (Object.keys(this.voices) as Lang[]).find((l) => this.voices[l] === m.voiceId) ?? 'en';
        this.o.onStatus?.({ kind: 'loading', percent: m.percent, lang });
        return;
      }
      const pending = this.waiting.get(m.id);
      if (!pending) return;
      this.waiting.delete(m.id);
      if (m.type === 'audio') pending.resolve({ wav: m.wav, seconds: m.seconds });
      else pending.reject(new Error(m.detail));
    };
    worker.onerror = (e) => {
      for (const [id, p] of this.waiting) {
        this.waiting.delete(id);
        p.reject(new Error(e.message));
      }
    };
    this.worker = worker;
    return worker;
  }
}

function defaultWorker(): Worker {
  return new Worker(new URL('./piper.worker.ts', import.meta.url), { type: 'module' });
}

/** Play WAV bytes through WebAudio; resolves with the clip's length in seconds when it has ended. */
export async function playWav(wav: ArrayBuffer, onStop: (stop: () => void) => void): Promise<number> {
  const context = sharedContext();
  const buffer = await context.decodeAudioData(wav.slice(0));
  await context.resume();
  return new Promise((resolve) => {
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve(buffer.duration);
    };
    source.onended = finish;
    onStop(() => {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
      finish();
    });
    source.start();
  });
}

let context: AudioContext | undefined;
function sharedContext(): AudioContext {
  context ??= new AudioContext();
  return context;
}
