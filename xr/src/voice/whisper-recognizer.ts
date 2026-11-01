/**
 * The on-device recognizer: the microphone, a worker with Silero and
 * Whisper, and nothing else. Works in any browser with WebAssembly, the
 * Meta Quest browser included, with no account, no key and, once the model
 * is cached, no network. The first use downloads the model (tens of MB);
 * the session is told how far along it is.
 */

import { microphoneSupported, openMicrophone } from './microphone';
import { transcribeRemote, type SpeechService } from './speech-service';
import type { Lang, Localized, Recognizer, RecognizerFailure, RecognizerStatus } from './types';
import type { FromWorker, ToWorker } from './whisper.worker';

/** Consecutive failures of the speech service before listening gives up. */
const REMOTE_FAILURES_TOLERATED = 3;

export type WhisperSize = 'tiny' | 'base' | 'small';

export interface WhisperRecognizerOptions {
  /** Which Whisper: tiny is quick, small hears Spanish best; base is the middle. */
  size?: WhisperSize;
  /** The app's vocabulary per language, Whisper's previous-text prompt; read at start. */
  hints: () => Localized<string>;
  /** Where the Silero ONNX file is served from. */
  vadUrl: string;
  /** The languages the app speaks (default both). */
  languages?: Lang[];
  /** The language the page is read in; wins a close call in detection. */
  preferredLanguage?: () => Lang;
  /** Prefer WebGPU when the browser offers it (default: yes). */
  webgpu?: boolean;
  /** How to make the worker; the default is Vite's `new Worker(new URL(...))`. */
  createWorker?: () => Worker;
  /**
   * A speech service to transcribe with instead of the model in the page:
   * the phrases are still found here (Silero), the words come from there.
   */
  server?: SpeechService;
}

export const WHISPER_MODELS: Record<WhisperSize, string> = {
  tiny: 'onnx-community/whisper-tiny',
  base: 'onnx-community/whisper-base',
  small: 'onnx-community/whisper-small',
};

export function whisperSize(value: string | null | undefined, fallback: WhisperSize = 'base'): WhisperSize {
  return value === 'tiny' || value === 'base' || value === 'small' ? value : fallback;
}

export class WhisperRecognizer implements Recognizer {
  readonly name: string;

  constructor(private readonly o: WhisperRecognizerOptions) {
    this.name = o.server ? 'whisper-server' : 'whisper';
  }

  available(): boolean {
    return typeof Worker !== 'undefined' && typeof WebAssembly !== 'undefined' && microphoneSupported();
  }

  listen(
    heard: (transcript: string, lang?: Lang) => void,
    failed: (reason: RecognizerFailure) => void,
    status?: (s: RecognizerStatus) => void,
  ): () => void {
    const worker = (this.o.createWorker ?? defaultWorker)();
    let closeMic: (() => void) | undefined;
    let stopped = false;
    const send = (m: ToWorker, transfer: Transferable[] = []) => worker.postMessage(m, transfer);
    const stop = () => {
      if (stopped) return;
      stopped = true;
      closeMic?.();
      send({ type: 'stop' });
      // Give the worker a moment to flush a phrase in progress, then end it.
      setTimeout(() => worker.terminate(), 5_000);
    };
    let remoteFailures = 0;
    const languages = this.o.languages ?? ['es', 'en'];
    const preferred = this.o.preferredLanguage?.();
    const hints = this.o.hints();
    const remote = (samples: Float32Array) => {
      if (!this.o.server) return;
      transcribeRemote(this.o.server, samples, { languages, preferred, hint: hints[preferred ?? 'es'] }).then(
        (t) => {
          remoteFailures = 0;
          if (t.text) heard(t.text, t.lang);
        },
        (err: Error) => {
          console.warn(`[voice] speech service failed: ${err.message}`);
          if (++remoteFailures >= REMOTE_FAILURES_TOLERATED) {
            stop();
            failed('network');
          }
        },
      );
    };
    worker.onmessage = (e: MessageEvent<FromWorker>) => {
      const m = e.data;
      if (m.type === 'progress') status?.({ kind: 'loading', percent: m.percent });
      else if (m.type === 'ready') status?.({ kind: 'ready' });
      else if (m.type === 'speech') status?.({ kind: m.speaking ? 'speech-start' : 'speech-end' });
      else if (m.type === 'segment') remote(m.samples);
      else if (m.type === 'transcript') {
        if (m.text) heard(m.text, m.lang);
      } else if (m.type === 'error') {
        // The person gets a sentence; the detail is for whoever reads the console.
        console.warn(`[voice] recognizer failed: ${m.detail}`);
        stop();
        failed(m.reason);
      }
    };
    worker.onerror = () => {
      stop();
      failed('model');
    };
    const device = this.o.webgpu !== false && 'gpu' in navigator ? 'webgpu' : 'wasm';
    send({
      type: 'load',
      model: WHISPER_MODELS[this.o.size ?? 'base'],
      device,
      vadUrl: this.o.vadUrl,
      hints,
      languages,
      preferred,
      mode: this.o.server ? 'segments' : 'local',
    });
    openMicrophone((frame) => {
      if (!stopped) send({ type: 'audio', samples: frame }, [frame.buffer]);
    }).then(
      (close) => {
        if (stopped) close();
        else closeMic = close;
      },
      (err: Error) => {
        stop();
        failed(err.message === 'unsupported' ? 'unsupported' : 'microphone');
      },
    );
    return stop;
  }
}

function defaultWorker(): Worker {
  return new Worker(new URL('./whisper.worker.ts', import.meta.url), { type: 'module' });
}
