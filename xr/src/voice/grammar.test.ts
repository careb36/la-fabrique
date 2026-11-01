import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { roomRegistry, taskItems, type RoomHandlers } from '../commands';
import type { Understanding } from './types';

/**
 * The grammar is judged against the phrase bank the recognizers are measured
 * with (`bench/phrases.json`): every written phrase must be understood as
 * meant, in both languages. A phrase the grammar misses is added to its
 * patterns or, when it is genuinely ambiguous, removed from the bank with a
 * reason; the bank is the contract.
 */

interface Phrase {
  id: string;
  lang: 'es' | 'en';
  text: string;
  intent: string;
  task?: string;
}
const bank = JSON.parse(readFileSync(new URL('../../bench/phrases.json', import.meta.url), 'utf8')) as {
  tasks: { id: string; title: string }[];
  phrases: Phrase[];
};

const noop = () => 'ok';
const handlers: RoomHandlers = {
  approve: noop, reject: noop, restart: noop, next: noop, pause: noop, resume: noop,
  recenter: noop, mute: noop, unmute: noop, launch: noop, status: noop,
};
const registry = roomRegistry(handlers, () => taskItems(bank.tasks));
const { grammar } = registry;

function meaning(u: Understanding | undefined): string {
  if (!u) return 'none';
  if (u.intent === 'launch') return u.item ? `launch:${u.item.id}` : 'launch:?';
  return u.intent;
}
function expected(p: Phrase): string {
  return p.intent === 'launch' ? `launch:${p.task}` : p.intent;
}

describe('the grammar against the phrase bank', () => {
  for (const lang of ['es', 'en'] as const) {
    it(`understands every ${lang} phrase as meant`, () => {
      const misses = bank.phrases
        .filter((p) => p.lang === lang)
        .map((p) => ({ p, got: meaning(grammar.understand(p.text)) }))
        .filter(({ p, got }) => got !== expected(p))
        .map(({ p, got }) => `${p.id} “${p.text}” → ${got} (wanted ${expected(p)})`);
      expect(misses).toEqual([]);
    });
  }

  it('answers in the language of the phrase it matched', () => {
    expect(grammar.understand('Aprobá')?.lang).toBe('es');
    expect(grammar.understand('Approve')?.lang).toBe('en');
  });
});

describe('rules a person expects', () => {
  it('a send back wins over an approval in the same sentence', () => {
    expect(meaning(grammar.understand("Don't approve it, send it back"))).toBe('reject');
    expect(meaning(grammar.understand('No la apruebo, mandala de vuelta'))).toBe('reject');
  });

  it('a negated approval is a send back', () => {
    expect(meaning(grammar.understand('No la apruebo'))).toBe('reject');
    expect(meaning(grammar.understand('No apruebes eso'))).toBe('reject');
  });

  it('a launch without a task asks for one', () => {
    const u = grammar.understand('Lanzá');
    expect(u?.intent).toBe('launch');
    expect(u?.needsItem).toBe(true);
    expect(grammar.understand('launch the thing')?.needsItem).toBe(true);
  });

  it('names a task by its place, the last one, or a word of its name', () => {
    expect(meaning(grammar.understand('start the second one'))).toBe('launch:csv');
    expect(meaning(grammar.understand('lanzá la última'))).toBe('launch:ci');
    expect(meaning(grammar.understand('arrancá la de la planilla'))).toBe('launch:csv');
    expect(grammar.itemOnly('la tercera')?.id).toBe('ci');
    expect(grammar.itemOnly('the password one')?.id).toBe('reset');
    expect(grammar.itemOnly('whatever')).toBeUndefined();
  });

  it('a restart beats a launch when both verbs are there', () => {
    expect(meaning(grammar.understand('Arrancá otra vez desde cero'))).toBe('restart');
  });

  it('chatter is nothing', () => {
    expect(grammar.understand('')).toBeUndefined();
    expect(grammar.understand('el arquitecto está pensando')).toBeUndefined();
    expect(grammar.understand('the room is nice')).toBeUndefined();
  });

  it('"para" alone pauses, "para" as a preposition does not', () => {
    expect(meaning(grammar.understand('pará'))).toBe('pause');
    expect(grammar.understand('es para mañana')).toBeUndefined();
  });
});
