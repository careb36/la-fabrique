import { describe, expect, it } from 'vitest';

import { compile, indexOf, nameWords, words } from './text';

describe('words', () => {
  it('lower-cases, drops accents and punctuation, keeps digits', () => {
    expect(words('¡Aprobá la Entrega, ya! 3 veces.')).toEqual(['aproba', 'la', 'entrega', 'ya', '3', 'veces']);
    expect(words("Don't")).toEqual(['don', 't']);
    expect(words('')).toEqual([]);
  });
});

describe('patterns', () => {
  it('matches a word sequence anywhere in the transcript', () => {
    expect(indexOf(compile('de vuelta'), words('mandala de vuelta, por favor'))).toBe(1);
    expect(indexOf(compile('de vuelta'), words('vuelta de'))).toBe(-1);
  });

  it('a stem matches every form of the verb', () => {
    const p = compile('aprob*');
    for (const form of ['aprobá', 'aprobala', 'aprobado', 'aprobar', 'aprobamos']) expect(indexOf(p, words(form))).toBe(0);
    expect(indexOf(p, words('apruebo'))).toBe(-1);
  });

  it('an underscore stands for any one word', () => {
    expect(indexOf(compile('send _ back'), words('please send it back'))).toBe(1);
    expect(indexOf(compile('send _ back'), words('send back'))).toBe(-1);
  });

  it('a caret wants the whole transcript', () => {
    expect(indexOf(compile('^no'), words('No.'))).toBe(0);
    expect(indexOf(compile('^no'), words('no la apruebo'))).toBe(-1);
  });

  it('a stem is normalized like the words it matches', () => {
    expect(indexOf(compile('contraseñ*'), words('la contraseña'))).toBe(1);
  });
});

describe('nameWords', () => {
  it('keeps the words that can name a thing', () => {
    expect(nameWords('CSV export of a sprint')).toEqual(['csv', 'export']);
    expect(nameWords('Pin the CI runner and actions')).toEqual(['pin', 'ci', 'runner', 'actions']);
  });
});
