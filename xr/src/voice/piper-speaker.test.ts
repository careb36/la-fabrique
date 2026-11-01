import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { PiperSpeaker } from './piper-speaker';
import { ORT_VERSION } from './ort-version';
import type { FromPiperWorker, ToPiperWorker } from './piper.worker';

/** A worker that answers each sentence with a WAV of its length, after a download. */
function fakeWorker() {
  const sent: ToPiperWorker[] = [];
  const worker = {
    onmessage: null as ((e: MessageEvent<FromPiperWorker>) => void) | null,
    onerror: null as ((e: ErrorEvent) => void) | null,
    postMessage(m: ToPiperWorker) {
      sent.push(m);
      const reply = (r: FromPiperWorker) => worker.onmessage?.({ data: r } as MessageEvent<FromPiperWorker>);
      queueMicrotask(() => {
        reply({ type: 'progress', voiceId: m.voiceId, percent: 50 });
        if (m.text.includes('fail')) reply({ type: 'error', id: m.id, detail: 'no voice' });
        else reply({ type: 'audio', id: m.id, wav: new ArrayBuffer(m.text.length), seconds: 0.2 });
      });
    },
    terminate() {},
  };
  return { worker: worker as unknown as Worker, sent };
}

describe('PiperSpeaker', () => {
  it('speaks each language with its voice, reports the download and what it spoke', async () => {
    const { worker, sent } = fakeWorker();
    const played: number[] = [];
    const status: unknown[] = [];
    const speaker = new PiperSpeaker({
      createWorker: () => worker,
      play: async (wav) => {
        played.push(wav.byteLength);
        return 1.5;
      },
      onStatus: (s) => status.push(s),
    });
    expect(speaker.available()).toBe(true);
    await speaker.say('Aprobada.', 'es');
    await speaker.say('Approved.', 'en');
    expect(sent.map((m) => m.voiceId)).toEqual(['es_MX-claude-high', 'en_US-hfc_female-medium']);
    expect(played).toEqual([9, 9]);
    expect(status).toContainEqual({ kind: 'loading', percent: 50, lang: 'es' });
    expect(status).toContainEqual({ kind: 'spoken', lang: 'en', synthesisSeconds: 0.2, audioSeconds: 1.5 });
  });

  it('a voice chosen by the application replaces the default', async () => {
    const { worker, sent } = fakeWorker();
    const speaker = new PiperSpeaker({ createWorker: () => worker, play: async () => 0, voices: { es: 'es_ES-davefx-medium' } });
    await speaker.say('Hola.', 'es');
    expect(sent[0].voiceId).toBe('es_ES-davefx-medium');
  });

  it('a failed synthesis rejects, so the session can move on', async () => {
    const { worker } = fakeWorker();
    const speaker = new PiperSpeaker({ createWorker: () => worker, play: async () => 0 });
    await expect(speaker.say('please fail', 'en')).rejects.toThrow('no voice');
  });

  it('says nothing for an empty sentence', async () => {
    const { worker, sent } = fakeWorker();
    const speaker = new PiperSpeaker({ createWorker: () => worker, play: async () => 0 });
    await speaker.say('   ', 'en');
    expect(sent).toEqual([]);
  });
});

describe('the ONNX runtime Piper loads', () => {
  it('is the version this app depends on', () => {
    const pkg = JSON.parse(readFileSync(new URL('../../package.json', import.meta.url), 'utf8')) as { dependencies: Record<string, string> };
    expect(pkg.dependencies['onnxruntime-web']).toBe(ORT_VERSION);
  });
});
