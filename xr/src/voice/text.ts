/**
 * Words and patterns: the pure text functions under the grammar.
 *
 * A transcript is reduced to lower-case words without accents or
 * punctuation, so "Aprobá." and "aproba" are the same word and a recognizer
 * that drops an accent costs nothing. Patterns are short word sequences:
 *
 * - `devolver`        a word, as written;
 * - `aprob*`          any word starting with these letters (every form of the
 *                     verb: aprobá, aprobala, aprobado, aprobar);
 * - `send _ back`     `_` stands for any one word;
 * - `^no`             the whole transcript is this, and nothing else.
 */

export function words(text: string): string[] {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9 ]+/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
}

export interface Pattern {
  tokens: string[];
  /** The transcript must be exactly these words. */
  whole: boolean;
}

export function compile(pattern: string): Pattern {
  const whole = pattern.startsWith('^');
  const tokens: string[] = [];
  for (const piece of (whole ? pattern.slice(1) : pattern).split(/\s+/).filter(Boolean)) {
    if (piece === '_') tokens.push('_');
    else if (piece.endsWith('*')) tokens.push(`${words(piece.slice(0, -1)).join('')}*`);
    else tokens.push(...words(piece));
  }
  return { tokens, whole };
}

function tokenMatches(token: string, word: string): boolean {
  if (token === '_') return true;
  if (token.endsWith('*')) return word.startsWith(token.slice(0, -1));
  return token === word;
}

/** The index where the pattern starts in `said`, or -1. */
export function indexOf(pattern: Pattern, said: string[]): number {
  const { tokens, whole } = pattern;
  if (whole) return tokens.length === said.length && tokens.every((t, i) => tokenMatches(t, said[i])) ? 0 : -1;
  for (let i = 0; i + tokens.length <= said.length; i++) {
    if (tokens.every((t, j) => tokenMatches(t, said[i + j]))) return i;
  }
  return -1;
}

/** Words that name nothing on their own, in either language. */
export const STOP_WORDS = new Set([
  'a', 'an', 'the', 'of', 'and', 'one', 'this', 'that', 'it', 'to', 'with', 'for', 'on', 'in',
  'el', 'la', 'los', 'las', 'de', 'del', 'un', 'una', 'y', 'con', 'al', 'lo', 'le', 'que', 'esta', 'este', 'esa', 'ese',
  'task', 'tarea', 'sprint',
]);

/** The words of a label that can name it: not stop words, not single letters. */
export function nameWords(text: string): string[] {
  return words(text).filter((w) => w.length > 1 && !STOP_WORDS.has(w));
}
