import { describe, expect, it } from 'vitest';

import { fromAnswer, intentResolver } from './intent-service';
import { CommandRegistry } from './registry';
import { VoiceSession } from './session';
import type { Action, Lang, Recognizer, Speaker, Understanding, VoiceEvent } from './types';

const actions: Action[] = [
  {
    id: 'approve',
    label: { es: 'aprobar', en: 'approve' },
    phrases: { es: ['aprob*'], en: ['approv*'] },
    risk: 'confirm',
    confirm: { es: '¿Apruebo?', en: 'Approve?' },
    run: () => ({ es: 'Aprobada.', en: 'Approved.' }),
  },
  {
    id: 'pause',
    label: { es: 'pausar', en: 'pause' },
    phrases: { es: ['pausa*'], en: ['pause*'] },
    run: () => ({ es: 'En pausa.', en: 'Paused.' }),
  },
  {
    id: 'launch',
    label: { es: 'lanzar una tarea', en: 'launch a task' },
    phrases: { es: ['lanz*'], en: ['launch*'] },
    items: () => [{ id: 'csv', label: { es: 'Exportar CSV', en: 'CSV export' } }],
    run: ({ item }) => `Launched ${item?.id}.`,
  },
];
const registry = new CommandRegistry(actions);

describe('fromAnswer', () => {
  it('turns the service answer into an understanding the session acts on', () => {
    expect(fromAnswer({ intent: 'pause', item: null, reply: null }, registry, 'es')).toEqual({ intent: 'pause', lang: 'es', reply: undefined });
    expect(fromAnswer({ intent: 'launch', item: 'csv', reply: 'Dale.' }, registry, 'es')).toMatchObject({ intent: 'launch', item: { id: 'csv' }, reply: 'Dale.' });
    expect(fromAnswer({ intent: 'launch', item: 'nope', reply: null }, registry, 'en')).toMatchObject({ intent: 'launch', needsItem: true });
    expect(fromAnswer({ intent: 'yes', item: null, reply: null }, registry, 'en')).toEqual({ intent: 'yes', lang: 'en', reply: undefined });
  });

  it('an action outside the registry is nothing, unless the model said something to say', () => {
    expect(fromAnswer({ intent: 'format_disk', item: null, reply: null }, registry, 'es')).toBeUndefined();
    expect(fromAnswer({ intent: null, item: null, reply: '¿Querés pausar o seguir?' }, registry, 'es')).toEqual({ intent: 'none', lang: 'es', reply: '¿Querés pausar o seguir?' });
    expect(fromAnswer({ intent: null, item: null, reply: '  ' }, registry, 'es')).toBeUndefined();
  });
});

describe('intentResolver', () => {
  it('posts the transcript and the catalogue with the items, and reads the answer', async () => {
    const calls: { url: string; body: unknown }[] = [];
    const fetchFake = (async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), body: JSON.parse(init?.body as string) });
      return new Response(JSON.stringify({ intent: 'launch', item: 'csv', reply: null }), { status: 200 });
    }) as typeof fetch;
    const resolve = intentResolver({ service: { url: 'https://speech.example/', apiKey: 'k', fetch: fetchFake }, registry, context: 'the room' });
    const u = await resolve('dale con la planilla', 'es');
    expect(u).toMatchObject({ intent: 'launch', item: { id: 'csv' } });
    expect(calls[0].url).toBe('https://speech.example/v1/intent');
    expect(calls[0].body).toEqual({
      transcript: 'dale con la planilla',
      language: 'es',
      context: 'the room',
      actions: [
        { id: 'approve', label: 'aprobar', description: 'pide confirmación', items: [] },
        { id: 'pause', label: 'pausar', description: '', items: [] },
        { id: 'launch', label: 'lanzar una tarea', description: '', items: [{ id: 'csv', label: 'Exportar CSV' }] },
      ],
    });
  });

  it('fails loudly on a refusal, so the session falls back to its own words', async () => {
    const resolve = intentResolver({ service: { url: 'https://x', fetch: (async () => new Response('', { status: 503 })) as typeof fetch }, registry });
    await expect(resolve('hola', 'es')).rejects.toThrow('503');
  });
});

describe('VoiceSession with a model behind the grammar', () => {
  function harness(intent: (t: string, l: Lang) => Promise<Understanding | undefined>) {
    let heard: ((t: string, l?: Lang) => void) | undefined;
    const recognizer: Recognizer = { available: () => true, listen: (h) => ((heard = h), () => {}) };
    const said: string[] = [];
    const speaker: Speaker = { available: () => true, say: async (t) => void said.push(t), stop() {} };
    const events: VoiceEvent[] = [];
    let now = 1_000_000;
    const session = new VoiceSession({ registry, recognizer, speaker, language: () => 'es', intent, onEvent: (e) => events.push(e), now: () => now });
    session.start();
    const settle = async () => {
      for (let i = 0; i < 5; i++) await Promise.resolve();
      now += 5_000;
    };
    return { say: (t: string) => heard?.(t), said, events, settle };
  }

  it('asks the model only for what the grammar missed, and acts on its answer with the same confirmations', async () => {
    const asked: string[] = [];
    const h = harness(async (t) => {
      asked.push(t);
      return { intent: 'approve', lang: 'es' };
    });
    h.say('pausá');
    await h.settle();
    expect(asked).toEqual([]);
    h.say('me parece que esto ya quedó bien terminado');
    await h.settle();
    expect(asked).toHaveLength(1);
    expect(h.events.some((e) => e.kind === 'status' && e.text === 'Pensando...')).toBe(true);
    expect(h.said.at(-1)).toBe('¿Apruebo? Decí sí o no.');
  });

  it('says what the model suggested when it understood no action', async () => {
    const h = harness(async () => ({ intent: 'none', lang: 'es', reply: '¿Querés pausar o seguir?' }));
    h.say('hmm no sé');
    await h.settle();
    expect(h.said.at(-1)).toBe('¿Querés pausar o seguir?');
  });

  it('falls back to its own words when the model fails or has nothing', async () => {
    const failing = harness(async () => {
      throw new Error('down');
    });
    failing.say('hmm');
    await failing.settle();
    expect(failing.said.at(-1)).toBe('No entendí. Decí «ayuda» para oír las órdenes.');
    const empty = harness(async () => undefined);
    empty.say('hmm');
    await empty.settle();
    expect(empty.said.at(-1)).toBe('No entendí. Decí «ayuda» para oír las órdenes.');
  });

  it('a stale answer, overtaken by a newer phrase, is dropped', async () => {
    let release: ((u: Understanding | undefined) => void) | undefined;
    const h = harness(() => new Promise((resolve) => (release = resolve)));
    h.say('eh, bueno');
    const first = release;
    h.say('pausá');
    await h.settle();
    expect(h.said).toEqual(['En pausa.']);
    first?.({ intent: 'approve', lang: 'es' });
    await h.settle();
    expect(h.said).toEqual(['En pausa.']);
  });
});
