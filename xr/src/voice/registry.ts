/**
 * The application's actions, as the voice layer sees them.
 *
 * The registry is the one place an application touches: it declares what
 * can be asked for (`ActionSpec`, data) and what each does (`run`). From it
 * the layer builds the grammar, the help sentence and the confirmations.
 */

import { Grammar, type IntentSpec } from './grammar';
import { listOf, message } from './messages';
import type { Action, Lang, Localized } from './types';

/** The layer's own intents, answered by the session, not by an action. */
const BUILTINS: IntentSpec[] = [
  {
    intent: 'help',
    phrases: {
      es: ['ayuda', 'que puedo decir', 'que ordenes', 'que comandos', 'que entend*', 'que podes hacer', 'que sabes hacer'],
      en: ['help', 'what can i say', 'which commands', 'what commands', 'what do you understand', 'what can you do'],
    },
  },
  {
    intent: 'no',
    phrases: {
      es: ['^no', 'cancel*', 'mejor no', 'dejalo', 'olvidalo', 'no hagas nada'],
      en: ['^no', 'cancel*', 'never mind', 'leave it', 'forget it', 'do nothing'],
    },
  },
  {
    intent: 'yes',
    phrases: {
      es: ['^si', '^si dale', 'si dale', 'confirm*', 'exacto', 'hacelo', '^dale', 'correcto', '^ok', '^okay', 'adelante'],
      en: ['^yes', 'yes', 'yeah', 'yep', 'confirm*', 'do it', 'go ahead', 'exactly', 'sure', 'correct', '^ok', '^okay'],
    },
  },
];

export class CommandRegistry {
  readonly grammar: Grammar;
  private readonly byId = new Map<string, Action>();

  /** `actions` in priority order: the first whose phrase matches wins. */
  constructor(readonly actions: Action[], negations: Record<string, string> = {}) {
    for (const a of actions) this.byId.set(a.id, a);
    const specs: IntentSpec[] = actions.map((a) => ({
      intent: a.id,
      phrases: a.phrases,
      items: a.items,
      negatedBecomes: negations[a.id],
    }));
    this.grammar = new Grammar([...specs, ...BUILTINS]);
  }

  action(id: string): Action | undefined {
    return this.byId.get(id);
  }

  /** "You can say: approve, send back, pause ..." in the language asked. */
  help(lang: Lang): string {
    return message(lang, 'help', { list: listOf(lang, this.actions.map((a) => a.label[lang])) });
  }

  /** The actions' labels, for a panel or a help page. */
  labels(): Localized<string[]> {
    return { es: this.actions.map((a) => a.label.es), en: this.actions.map((a) => a.label.en) };
  }
}
