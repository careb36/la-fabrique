/// <reference lib="webworker" />
/**
 * The on-device recognizer's worker: Silero decides when a phrase was
 * said, Whisper says what. Off the main thread, so the room keeps drawing
 * its frames while a phrase is transcribed.
 *
 * Protocol (main → worker): `load` once, then `audio` with 16 kHz float
 * samples as they are captured, `stop` to flush and end. Worker → main:
 * `progress` while the model downloads (cached by the browser afterwards),
 * `ready`, `speech` when a phrase starts and ends (for the panel),
 * `transcript` with the words and the language, `error` with a reason.
 */

import { env, pipeline, Tensor } from '@huggingface/transformers';
// The same ONNX runtime transformers.js uses (same package, same subpath),
// so the browser loads one copy and Silero rides on the backend it set up.
import * as ort from 'onnxruntime-web/webgpu';

import { Endpointer, padded } from './endpointer';
import { SileroVad } from './silero';
import { detectLanguage, transcribe, type ProcessorLike, type TokenizerLike, type WhisperLike } from './whisper-core';
import type { Lang, Localized } from './types';

export interface LoadMessage {
  type: 'load';
  /** A transformers.js model id, such as onnx-community/whisper-base. */
  model: string;
  /** 'webgpu' or 'wasm'. */
  device: 'webgpu' | 'wasm';
  /** Where the Silero ONNX file is served from. */
  vadUrl: string;
  /** The app's vocabulary per language, Whisper's previous-text prompt. */
  hints: Localized<string>;
  /** The languages the app speaks; the likeliest is chosen per phrase. */
  languages: Lang[];
  /** The language the page is read in: wins a close call. */
  preferred?: Lang;
  /**
   * 'local' (default) transcribes here; 'segments' only finds the phrases
   * and hands them back, for a recognizer that sends them to a server.
   */
  mode?: 'local' | 'segments';
}
export interface AudioMessage {
  type: 'audio';
  samples: Float32Array;
}
export interface StopMessage {
  type: 'stop';
}
export type ToWorker = LoadMessage | AudioMessage | StopMessage;

export type FromWorker =
  | { type: 'progress'; percent: number; file: string }
  | { type: 'ready' }
  | { type: 'speech'; speaking: boolean }
  | { type: 'transcript'; text: string; lang: Lang; seconds: number }
  | { type: 'segment'; samples: Float32Array }
  | { type: 'error'; reason: 'model' | 'microphone' | 'network'; detail: string };

const post = (m: FromWorker, transfer: Transferable[] = []) => (self as unknown as Worker).postMessage(m, transfer);

interface Asr {
  model: WhisperLike;
  processor: ProcessorLike;
  tokenizer: TokenizerLike;
}

interface Loaded {
  /** Absent in 'segments' mode: the phrases go elsewhere to be transcribed. */
  asr?: Asr;
  vad: SileroVad;
  hints: Localized<string>;
  languages: Lang[];
  preferred?: Lang;
}

let loaded: Loaded | undefined;
const endpointer = new Endpointer();
let queue: Promise<void> = Promise.resolve();
let wasSpeaking = false;

/** WebGPU only when the browser can hand out an adapter; the flag alone is not enough. */
async function usableDevice(wanted: 'webgpu' | 'wasm'): Promise<'webgpu' | 'wasm'> {
  if (wanted !== 'webgpu') return 'wasm';
  const gpu = (navigator as unknown as { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
  try {
    return gpu && (await gpu.requestAdapter()) ? 'webgpu' : 'wasm';
  } catch {
    return 'wasm';
  }
}

async function loadAsr(m: LoadMessage): Promise<Asr> {
  const seen = new Map<string, number>();
  const device = await usableDevice(m.device);
  const asr = (await pipeline('automatic-speech-recognition', m.model, {
    dtype: { encoder_model: 'q8', decoder_model_merged: 'q8' },
    device,
    progress_callback: (p: { status: string; file?: string; progress?: number }) => {
      if (p.status !== 'progress' || !p.file) return;
      seen.set(p.file, p.progress ?? 0);
      const values = [...seen.values()];
      post({ type: 'progress', percent: Math.round(values.reduce((a, b) => a + b, 0) / values.length), file: p.file });
    },
  })) as unknown as Asr;
  return { model: asr.model, processor: asr.processor, tokenizer: asr.tokenizer };
}

async function load(m: LoadMessage): Promise<void> {
  env.allowLocalModels = false;
  const asr = m.mode === 'segments' ? undefined : await loadAsr(m);
  // Silero: small enough for WASM whatever Whisper runs on.
  const response = await fetch(m.vadUrl);
  if (!response.ok) throw new Error(`voice detector not found at ${m.vadUrl} (${response.status})`);
  const session = await ort.InferenceSession.create(await response.arrayBuffer(), { executionProviders: ['wasm'] });
  const vad = new SileroVad(session as never, (data, dims) => new ort.Tensor('float32', data, dims) as never);
  loaded = { asr, vad, hints: m.hints, languages: m.languages, preferred: m.preferred };
  post({ type: 'ready' });
}

async function onAudio(samples: Float32Array): Promise<void> {
  if (!loaded) return;
  for (const { window, probability } of await loaded.vad.feed(samples)) {
    const phrase = endpointer.push(window, probability);
    if (endpointer.isSpeaking !== wasSpeaking) {
      wasSpeaking = endpointer.isSpeaking;
      post({ type: 'speech', speaking: wasSpeaking });
    }
    if (phrase) await heard(phrase);
  }
}

async function heard(phrase: Float32Array): Promise<void> {
  if (!loaded) return;
  if (!loaded.asr) {
    post({ type: 'segment', samples: phrase }, [phrase.buffer]);
    return;
  }
  const { model, processor, tokenizer } = loaded.asr;
  const started = performance.now();
  const audio = padded(phrase);
  const lang =
    loaded.languages.length === 1
      ? loaded.languages[0]
      : await detectLanguage(model, processor, Tensor as never, audio, loaded.languages, loaded.preferred);
  const text = await transcribe(model, processor, tokenizer, audio, lang, loaded.hints[lang]);
  post({ type: 'transcript', text, lang, seconds: (performance.now() - started) / 1000 });
}

self.onmessage = (e: MessageEvent<ToWorker>) => {
  const m = e.data;
  queue = queue
    .then(async () => {
      if (m.type === 'load') await load(m);
      else if (m.type === 'audio') await onAudio(m.samples);
      else if (m.type === 'stop') {
        const rest = endpointer.flush();
        if (rest) await heard(rest);
        loaded?.vad.reset();
      }
    })
    .catch((err: unknown) => {
      const detail = err instanceof Error ? err.message : String(err);
      post({ type: 'error', reason: /fetch|network|Failed to load/i.test(detail) ? 'network' : 'model', detail });
    });
};
