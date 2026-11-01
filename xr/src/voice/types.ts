/**
 * The voice layer's vocabulary of types.
 *
 * The layer knows nothing about the application it controls: an application
 * describes its actions (`ActionSpec`), the layer listens, understands and
 * confirms, and calls the action's `run`. Everything the layer says to the
 * person exists in both languages (`Localized`); the application's own
 * sentences come back from `run` the same way.
 */

export type Lang = 'es' | 'en';

export const LANGS: readonly Lang[] = ['es', 'en'];

export type Localized<T> = Record<Lang, T>;

/** A sentence in one language, or in both for the layer to pick from. */
export type Speech = string | Localized<string>;

/**
 * Something the person can ask for by its place or its name: a task, a
 * target, a record. `words` are what a person calls it in each language,
 * beyond its label; the grammar also reads the label's own words.
 */
export interface Item {
  id: string;
  label: Localized<string>;
  words?: Partial<Localized<string[]>>;
}

/** What running an action leaves to say. */
export interface Outcome {
  speech: Speech;
  /** False when the action could not be done; the layer says `speech` either way. */
  ok?: boolean;
}

export interface RunContext {
  /** The item the person named, for an action that takes one. */
  item?: Item;
  /** The language the person spoke in. */
  lang: Lang;
}

/**
 * One thing the application can do on request.
 *
 * `phrases` are patterns the grammar matches in each language (see
 * `grammar.ts` for the syntax). `risk: 'confirm'` makes the layer ask
 * before running and run only on a yes; `confirm` is that question, with
 * `{item}` for the item's label.
 */
export interface ActionSpec {
  id: string;
  /** What the action is called when the layer lists what it can do. */
  label: Localized<string>;
  phrases: Localized<string[]>;
  /**
   * Whole words a recognizer should expect for this action, where the
   * phrases are stems ("aprob*" is not a word a model can be primed with).
   */
  hint?: Localized<string[]>;
  risk?: 'safe' | 'confirm';
  confirm?: Localized<string>;
  /** The items a person may name; an action with items needs one named. */
  items?: () => Item[];
  /** Said when the action takes an item and none was named: `{items}` lists them. */
  whichItem?: Localized<string>;
  /** Why the action cannot run right now; said instead of asking or running. */
  blocked?: () => Speech | undefined;
  /** What the action would act on now, for `{item}` in `confirm` when no item was named. */
  subject?: () => Speech | undefined;
}

export interface Action extends ActionSpec {
  /** Does it, and says what happened: a sentence, a pair, or an `Outcome`. */
  run: (ctx: RunContext) => Outcome | Speech;
}

/** What the grammar made of a transcript. */
export interface Understanding {
  /** An action id, or one of the layer's own intents. */
  intent: string;
  /** The language of the words matched, when they tell it. */
  lang?: Lang;
  item?: Item;
  /** The action takes an item and the transcript named none. */
  needsItem?: boolean;
}

/** The layer's own intents, never an application's. */
export const BUILTIN_INTENTS = ['yes', 'no', 'help'] as const;
export type BuiltinIntent = (typeof BUILTIN_INTENTS)[number];

export interface Recognizer {
  /** Whether this recognizer can work here at all (an API present, a model reachable). */
  available(): boolean;
  /**
   * Listen until the returned function is called, handing every final
   * transcript (and the language heard, when known) to `heard`. `failed`
   * ends listening with a reason the layer tells the person.
   */
  listen(heard: (transcript: string, lang?: Lang) => void, failed: (reason: RecognizerFailure) => void): () => void;
}

export type RecognizerFailure = 'unsupported' | 'microphone' | 'network' | 'model';

export interface Speaker {
  available(): boolean;
  /** Says the text; resolves when it has been said (or could not be). */
  say(text: string, lang: Lang): Promise<void>;
  stop(): void;
}

export type VoiceEvent =
  | { kind: 'listening'; text: string; lang: Lang }
  | { kind: 'heard'; text: string; lang: Lang }
  | { kind: 'said'; text: string; lang: Lang }
  | { kind: 'stopped'; text: string; lang: Lang }
  | { kind: 'error'; text: string; lang: Lang; reason: RecognizerFailure };
