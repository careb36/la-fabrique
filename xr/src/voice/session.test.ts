import { describe, expect, it } from 'vitest';

import { CommandRegistry } from './registry';
import { PENDING_MS, VoiceSession } from './session';
import type { Action, Lang, Recognizer, Speaker, VoiceEvent } from './types';

/** A recognizer the test speaks through, and a speaker that records. */
function harness(actions: Action[], language: Lang = 'es') {
  let heard: ((t: string, l?: Lang) => void) | undefined;
  let failed: ((r: 'microphone') => void) | undefined;
  const recognizer: Recognizer = {
    available: () => true,
    listen(h, f) {
      heard = h;
      failed = f;
      return () => {
        heard = undefined;
      };
    },
  };
  const said: string[] = [];
  let release: (() => void) | undefined;
  const speaker: Speaker = {
    available: () => true,
    say(text) {
      said.push(text);
      // Speaking takes time: the test ends it with `done()`.
      return new Promise<void>((resolve) => {
        release = resolve;
      });
    },
    stop() {},
  };
  const events: VoiceEvent[] = [];
  log.length = 0;
  let now = 1_000_000;
  const session = new VoiceSession({
    registry: new CommandRegistry(actions, { approve: 'reject' }),
    recognizer,
    speaker,
    language: () => language,
    onEvent: (e) => events.push(e),
    now: () => now,
  });
  const done = async () => {
    release?.();
    release = undefined;
    await Promise.resolve();
    await Promise.resolve();
    now += 1000; // past the echo window
  };
  return {
    session,
    said,
    events,
    say: (t: string, l?: Lang) => heard?.(t, l),
    fail: () => failed?.('microphone'),
    done,
    advance: (ms: number) => {
      now += ms;
    },
  };
}

const log: string[] = [];
const actions: Action[] = [
  {
    id: 'reject',
    label: { es: 'devolver', en: 'send back' },
    phrases: { es: ['devolv*', 'rechaz*'], en: ['send _ back', 'reject*'] },
    risk: 'confirm',
    confirm: { es: '¿Devuelvo {item}?', en: 'Send {item} back?' },
    run: () => {
      log.push('reject');
      return { es: 'Devuelta.', en: 'Sent back.' };
    },
  },
  {
    id: 'approve',
    label: { es: 'aprobar', en: 'approve' },
    phrases: { es: ['aprob*', 'aprueb*'], en: ['approv*'] },
    risk: 'confirm',
    confirm: { es: '¿Apruebo la entrega?', en: 'Approve the delivery?' },
    run: () => {
      log.push('approve');
      return { es: 'Aprobada.', en: 'Approved.' };
    },
  },
  {
    id: 'pause',
    label: { es: 'pausar', en: 'pause' },
    phrases: { es: ['pausa*'], en: ['pause*'] },
    run: () => {
      log.push('pause');
      return { speech: { es: 'En pausa.', en: 'Paused.' } };
    },
  },
  {
    id: 'launch',
    label: { es: 'lanzar una tarea', en: 'launch a task' },
    phrases: { es: ['lanz*'], en: ['launch*'] },
    items: () => [
      { id: 'a', label: { es: 'Alta de usuarios', en: 'User sign-up' } },
      { id: 'b', label: { es: 'Exportar CSV', en: 'CSV export' } },
    ],
    run: ({ item }) => {
      log.push(`launch:${item?.id}`);
      return `Launched ${item?.label.en}.`;
    },
  },
];

describe('VoiceSession', () => {
  it('runs a safe action at once and answers in the language spoken', async () => {
    const h = harness(actions);
    h.session.start();
    expect(h.events[0]).toMatchObject({ kind: 'listening', lang: 'es' });
    h.say('pause please');
    expect(h.said).toEqual(['Paused.']);
    expect(log.pop()).toBe('pause');
    await h.done();
    h.say('poné pausa');
    expect(h.said.at(-1)).toBe('En pausa.');
  });

  it('asks before an action that must be confirmed, and runs it on a yes', async () => {
    const h = harness(actions);
    h.session.start();
    h.say('aprobá');
    expect(h.said.at(-1)).toBe('¿Apruebo la entrega? Decí sí o no.');
    expect(log.includes('approve')).toBe(false);
    await h.done();
    h.say('sí');
    expect(log.pop()).toBe('approve');
    expect(h.said.at(-1)).toBe('Aprobada.');
  });

  it('a no cancels, and a yes with nothing pending does nothing', async () => {
    const h = harness(actions, 'en');
    h.session.start();
    h.say('approve it');
    await h.done();
    h.say('no');
    expect(h.said.at(-1)).toBe('Cancelled.');
    expect(log.includes('approve')).toBe(false);
    await h.done();
    h.say('yes');
    expect(h.said.at(-1)).toBe('Nothing to confirm.');
  });

  it('a question forgotten expires instead of firing later', async () => {
    const h = harness(actions, 'en');
    h.session.start();
    h.say('approve');
    await h.done();
    h.advance(PENDING_MS + 1);
    h.say('yes');
    expect(log.includes('approve')).toBe(false);
    expect(h.events.some((e) => e.kind === 'said' && e.text === 'Time ran out; nothing was done.')).toBe(true);
    expect(h.said.at(-1)).toBe('Nothing to confirm.');
  });

  it('a new request replaces the pending question', async () => {
    const h = harness(actions, 'en');
    h.session.start();
    h.say('approve');
    await h.done();
    h.say('pause');
    expect(log.pop()).toBe('pause');
    await h.done();
    h.say('yes');
    expect(h.said.at(-1)).toBe('Nothing to confirm.');
  });

  it('a launch without a task asks which, and takes the answer alone', async () => {
    const h = harness(actions, 'es');
    h.session.start();
    h.say('lanzá');
    expect(h.said.at(-1)).toBe('¿Cuál? Alta de usuarios o Exportar CSV.');
    await h.done();
    h.say('la segunda');
    expect(log.pop()).toBe('launch:b');
  });

  it('ignores what the microphone hears while the speaker talks', async () => {
    const h = harness(actions, 'en');
    h.session.start();
    h.say('pause');
    expect(h.said).toEqual(['Paused.']);
    h.say('pause'); // the speaker's own "Paused." coming back, or anything else
    expect(h.said).toEqual(['Paused.']);
    await h.done();
    h.say('pause');
    expect(h.said).toEqual(['Paused.', 'Paused.']);
  });

  it('a speaker that never finishes does not leave the session deaf for good', () => {
    const h = harness(actions, 'en');
    h.session.start();
    h.say('pause');
    expect(h.said).toEqual(['Paused.']);
    // The speaker never resolves; after a generous estimate the session listens again.
    h.advance(2_000 + 400 + 1);
    h.say('pause');
    expect(h.said).toEqual(['Paused.', 'Paused.']);
  });

  it('help lists the actions in the language asked', () => {
    const h = harness(actions, 'en');
    h.session.start();
    h.say('ayuda');
    expect(h.said.at(-1)).toBe('Podés decir: devolver, aprobar, pausar o lanzar una tarea.');
  });

  it('says it did not understand, in the page language when the phrase tells nothing', () => {
    const h = harness(actions, 'en');
    h.session.start();
    h.say('what a nice room');
    expect(h.said.at(-1)).toBe('I did not catch that. Say "help" to hear the commands.');
  });

  it('a recognizer failure stops listening with the reason', () => {
    const h = harness(actions, 'es');
    h.session.start();
    h.fail();
    expect(h.session.listening).toBe(false);
    expect(h.events.at(-1)).toMatchObject({ kind: 'error', reason: 'microphone', text: 'Necesito el micrófono para escucharte.' });
  });

  it('stop ends listening and drops any pending question', async () => {
    const h = harness(actions, 'es');
    h.session.start();
    h.say('aprobá');
    await h.done();
    h.session.stop();
    expect(h.events.at(-1)).toMatchObject({ kind: 'stopped' });
    h.session.start();
    h.say('sí');
    expect(h.said.at(-1)).toBe('No hay nada que confirmar.');
  });
});
