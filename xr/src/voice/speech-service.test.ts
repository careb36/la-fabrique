import { describe, expect, it } from 'vitest';

import { ServerSpeaker, transcribeRemote } from './speech-service';
import { encodeWav } from './wav';

function fakeFetch(answer: (url: string, init: RequestInit) => Response) {
  const calls: { url: string; init: RequestInit }[] = [];
  const f = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    return answer(String(url), init ?? {});
  }) as typeof fetch;
  return { fetch: f, calls };
}

describe('encodeWav', () => {
  it('writes a 16-bit mono PCM header and the clipped samples', () => {
    const bytes = encodeWav(new Float32Array([0, 0.5, 2, -2]), 16_000);
    const view = new DataView(bytes);
    expect(String.fromCharCode(...new Uint8Array(bytes, 0, 4))).toBe('RIFF');
    expect(String.fromCharCode(...new Uint8Array(bytes, 8, 4))).toBe('WAVE');
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(8);
    expect(view.getInt16(44, true)).toBe(0);
    expect(view.getInt16(46, true)).toBe(16384);
    expect(view.getInt16(48, true)).toBe(32767);
    expect(view.getInt16(50, true)).toBe(-32767);
  });
});

describe('transcribeRemote', () => {
  it('posts the phrase as WAV with the languages, the prior, the hint and the key', async () => {
    const { fetch, calls } = fakeFetch(() => new Response(JSON.stringify({ text: 'aprobá', language: 'es', seconds: 0.4 }), { status: 200 }));
    const result = await transcribeRemote({ url: 'https://speech.example/', apiKey: 'k', fetch }, new Float32Array(1600), {
      languages: ['es', 'en'],
      preferred: 'es',
      hint: 'Aprobá. Devolvela.',
    });
    expect(result).toEqual({ text: 'aprobá', lang: 'es', seconds: 0.4 });
    const url = new URL(calls[0].url);
    expect(url.pathname).toBe('/v1/transcribe');
    expect(url.searchParams.get('languages')).toBe('es,en');
    expect(url.searchParams.get('preferred')).toBe('es');
    expect(url.searchParams.get('prompt')).toBe('Aprobá. Devolvela.');
    expect((calls[0].init.headers as Record<string, string>)['X-API-Key']).toBe('k');
    expect((calls[0].init.body as ArrayBuffer).byteLength).toBe(44 + 1600 * 2);
  });

  it('fails loudly when the service refuses', async () => {
    const { fetch } = fakeFetch(() => new Response('no', { status: 401 }));
    await expect(transcribeRemote({ url: 'https://speech.example', fetch }, new Float32Array(10), { languages: ['en'] })).rejects.toThrow('401');
  });
});

describe('ServerSpeaker', () => {
  it('asks for the sentence in the language and voice, plays what comes back', async () => {
    const { fetch, calls } = fakeFetch(() => new Response(new ArrayBuffer(100), { status: 200, headers: { 'Content-Type': 'audio/wav' } }));
    const played: number[] = [];
    const status: unknown[] = [];
    const speaker = new ServerSpeaker({
      service: { url: 'https://speech.example', fetch },
      voices: { es: 'ef_dora' },
      play: async (wav) => {
        played.push(wav.byteLength);
        return 1.2;
      },
      onStatus: (s) => status.push(s),
    });
    expect(speaker.available()).toBe(true);
    await speaker.say('Aprobada.', 'es');
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ text: 'Aprobada.', language: 'es', voice: 'ef_dora' });
    expect(played).toEqual([100]);
    expect(status[0]).toMatchObject({ kind: 'spoken', lang: 'es', audioSeconds: 1.2 });
    await speaker.say('Approved.', 'en');
    expect(JSON.parse(calls[1].init.body as string).voice).toBeUndefined();
  });

  it('is not available without an address, and rejects on a refusal', async () => {
    expect(new ServerSpeaker({ service: { url: '' }, play: async () => 0 }).available()).toBe(false);
    const { fetch } = fakeFetch(() => new Response('', { status: 503 }));
    await expect(new ServerSpeaker({ service: { url: 'https://x', fetch }, play: async () => 0 }).say('hi', 'en')).rejects.toThrow('503');
  });
});
