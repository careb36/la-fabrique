/**
 * The deterministic understanding: a transcript in, an intent out.
 *
 * No model, no network, a few microseconds: this tier is always there, and
 * it is the only one in a page without a backend. It is built from the
 * application's actions plus the layer's own intents (yes, no, help), each
 * with its patterns per language (`text.ts` has the syntax).
 *
 * Rules a person would expect, written down:
 *
 * - intents are tried in a fixed order, so "don't approve it, send it back"
 *   is a send back: the action with the greater consequence comes first;
 * - an action can name what a negated match becomes ("no la apruebo" is a
 *   send back, not an approval);
 * - an action that takes an item resolves it from an ordinal ("la segunda",
 *   "the third one"), "the last one", or a word of the item's name or
 *   aliases; a trigger with no item is reported as `needsItem`;
 * - a transcript that names only an item (no trigger) resolves to that item
 *   alone, for the question "which one?" the layer may have just asked.
 */

import { compile, indexOf, nameWords, words, type Pattern } from './text';
import { LANGS, type Item, type Lang, type Localized, type Understanding } from './types';

export interface IntentSpec {
  intent: string;
  phrases: Localized<string[]>;
  /** The intent a match becomes when "no"/"not"/"don't" stands just before it. */
  negatedBecomes?: string;
  items?: () => Item[];
}

interface Compiled {
  intent: string;
  lang: Lang;
  pattern: Pattern;
  negatedBecomes?: string;
  items?: () => Item[];
}

const NEGATIONS = new Set(['no', 'not', 'dont', 'never', 'nunca', 'ni']);

const ORDINALS: Localized<string[][]> = {
  es: [
    ['primer', 'primera', 'primero'],
    ['segunda', 'segundo'],
    ['tercera', 'tercero'],
    ['cuarta', 'cuarto'],
    ['quinta', 'quinto'],
  ],
  en: [['first'], ['second'], ['third'], ['fourth'], ['fifth']],
};
const LAST: Localized<string[]> = { es: ['ultima', 'ultimo'], en: ['last'] };

/**
 * Words that belong to one language only, for a transcript whose matched
 * pattern is spelled the same in both ("pausa"/"pause" share a stem).
 */
const MARKERS: Localized<Set<string>> = {
  es: new Set(['el', 'la', 'los', 'las', 'de', 'del', 'que', 'por', 'favor', 'con', 'una', 'un', 'esta', 'esto', 'eso', 'lo', 'le', 'ya', 'bien', 'si', 'dale']),
  en: new Set(['the', 'it', 'this', 'that', 'please', 'back', 'with', 'to', 'of', 'is', 'are', 'me', 'my', 'one', 'okay', 'ok', 'yes']),
};

/** The language a transcript's small words give away, if they do. */
export function guessLang(said: string[]): Lang | undefined {
  const es = said.filter((w) => MARKERS.es.has(w)).length;
  const en = said.filter((w) => MARKERS.en.has(w)).length;
  if (es === en) return undefined;
  return es > en ? 'es' : 'en';
}

export class Grammar {
  private readonly compiled: Compiled[] = [];
  private readonly itemSources: (() => Item[])[] = [];

  /** `specs` in priority order: the first intent that matches wins. */
  constructor(specs: IntentSpec[]) {
    for (const spec of specs) {
      if (spec.items) this.itemSources.push(spec.items);
      for (const lang of LANGS) {
        for (const phrase of spec.phrases[lang] ?? []) {
          this.compiled.push({ intent: spec.intent, lang, pattern: compile(phrase), negatedBecomes: spec.negatedBecomes, items: spec.items });
        }
      }
    }
  }

  understand(transcript: string): Understanding | undefined {
    const said = words(transcript);
    if (!said.length) return undefined;
    const first = this.compiled.find((c) => indexOf(c.pattern, said) >= 0);
    if (!first) return undefined;
    // Every pattern of the winning intent that matches: one language, or
    // both when the word is spelled alike, and then the small words decide.
    const matches = this.compiled.filter((c) => c.intent === first.intent && indexOf(c.pattern, said) >= 0);
    const langs = new Set(matches.map((m) => m.lang));
    const lang = langs.size === 1 ? first.lang : guessLang(said);
    const at = indexOf(first.pattern, said);
    let intent = first.intent;
    if (first.negatedBecomes && said.slice(Math.max(0, at - 2), at).some((w) => NEGATIONS.has(w))) intent = first.negatedBecomes;
    if (!first.items) return { intent, lang };
    const item = resolveItem(said, first.items());
    return item ? { intent, lang, item } : { intent, lang, needsItem: true };
  }

  /** The item a transcript names on its own, if it names one. */
  itemOnly(transcript: string): Item | undefined {
    const said = words(transcript);
    for (const source of this.itemSources) {
      const item = resolveItem(said, source());
      if (item) return item;
    }
    return undefined;
  }
}

/** The item the words point at: by its place, "the last", or a word of its name. */
export function resolveItem(said: string[], items: Item[]): Item | undefined {
  if (!items.length) return undefined;
  for (const l of LANGS) {
    const n = ORDINALS[l].findIndex((names) => names.some((w) => said.includes(w)));
    if (n >= 0 && items[n]) return items[n];
    if (LAST[l].some((w) => said.includes(w))) return items[items.length - 1];
  }
  let best: { item: Item; hits: number } | undefined;
  for (const item of items) {
    const names = new Set<string>();
    for (const l of LANGS) {
      for (const w of nameWords(item.label[l] ?? '')) names.add(w);
      for (const w of item.words?.[l] ?? []) for (const x of words(w)) names.add(x);
    }
    const hits = said.filter((w) => names.has(w)).length;
    if (hits && (!best || hits > best.hits)) best = { item, hits };
  }
  return best?.item;
}
