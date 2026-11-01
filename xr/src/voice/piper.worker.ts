/// <reference lib="webworker" />
/**
 * The on-device voice's worker: Piper (VITS) turns a sentence into a WAV.
 *
 * Piper's voices are small neural models (about 60 MB each, downloaded once
 * and kept in the browser's private file system) that run on WASM at
 * speaking pace; the Meta Quest browser has no voice of its own. One
 * session per voice is kept, so the second sentence costs no setup.
 *
 * Protocol: `speak` {id, text, voiceId} → `audio` {id, wav} (16-bit PCM
 * WAV bytes) or `error` {id, detail}; `progress` while a voice downloads.
 */

import { TtsSession } from '@mintplex-labs/piper-tts-web';

import { ORT_CDN_BASE } from './ort-version';

export type ToPiperWorker = { type: 'speak'; id: number; text: string; voiceId: string };
export type FromPiperWorker =
  | { type: 'progress'; voiceId: string; percent: number }
  | { type: 'audio'; id: number; wav: ArrayBuffer; seconds: number }
  | { type: 'error'; id: number; detail: string };

const post = (m: FromPiperWorker, transfer: Transferable[] = []) => (self as unknown as Worker).postMessage(m, transfer);

const sessions = new Map<string, Promise<TtsSession>>();

function session(voiceId: string): Promise<TtsSession> {
  let s = sessions.get(voiceId);
  if (!s) {
    s = TtsSession.create({
      voiceId,
      progress: (p) => post({ type: 'progress', voiceId, percent: p.total ? Math.round((100 * p.loaded) / p.total) : 0 }),
      // The library's default points at an older runtime than the one bundled here.
      wasmPaths: { ...TtsSession.WASM_LOCATIONS, onnxWasm: ORT_CDN_BASE },
    });
    sessions.set(voiceId, s);
    s.catch(() => sessions.delete(voiceId));
  }
  return s;
}

let queue: Promise<void> = Promise.resolve();

self.onmessage = (e: MessageEvent<ToPiperWorker>) => {
  const m = e.data;
  if (m.type !== 'speak') return;
  queue = queue.then(async () => {
    const started = performance.now();
    try {
      const wav = await (await (await session(m.voiceId)).predict(m.text)).arrayBuffer();
      post({ type: 'audio', id: m.id, wav, seconds: (performance.now() - started) / 1000 }, [wav]);
    } catch (err: unknown) {
      post({ type: 'error', id: m.id, detail: err instanceof Error ? err.message : String(err) });
    }
  });
};
