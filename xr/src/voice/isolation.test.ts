import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { MESSAGES } from './messages';

/**
 * The voice layer is meant to move to its own package: nothing in this
 * folder may import from outside it (the room, three.js, the SDK). Tests
 * are exempt; they may read the bench's phrase bank.
 */
describe('the voice layer stands alone', () => {
  const folder = fileURLToPath(new URL('.', import.meta.url));
  const sources = readdirSync(folder).filter((f) => f.endsWith('.ts') && !f.endsWith('.test.ts'));

  it('has sources to check', () => {
    expect(sources.length).toBeGreaterThan(5);
  });

  for (const file of sources) {
    it(`${file} imports only its siblings`, () => {
      const text = readFileSync(`${folder}/${file}`, 'utf8');
      const specifiers = [...text.matchAll(/^\s*(?:import|export)\b[^'"]*from\s+['"]([^'"]+)['"]/gm)].map((m) => m[1]);
      const foreign = specifiers.filter((s) => !/^\.\/[a-z-]+$/.test(s));
      expect(foreign).toEqual([]);
    });
  }

  it('says everything in both languages, with the same keys', () => {
    expect(Object.keys(MESSAGES.en).sort()).toEqual(Object.keys(MESSAGES.es).sort());
    for (const [key, text] of Object.entries(MESSAGES.es)) expect(text, key).not.toBe(MESSAGES.en[key as keyof typeof MESSAGES.en]);
  });
});
