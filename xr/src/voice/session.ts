/**
 * One conversation between a person and an application.
 *
 * The session ties the pieces together: the recognizer hands it transcripts,
 * the grammar says what they mean, the registry runs the action or asks the
 * question (confirm, which item), the speaker says the answer. It keeps the
 * little state a conversation needs: a confirmation waiting for yes or no,
 * an action waiting for its item. Both expire, so a question asked and
 * forgotten never fires a minute later on an unrelated "sí".
 *
 * While the speaker talks, transcripts are dropped: in a headset the
 * microphone hears the speaker, and "Aprobado." must not approve again.
 */

import { listOf, message, pick } from './messages';
import type { CommandRegistry } from './registry';
import type { Action, Item, Lang, Recognizer, RecognizerFailure, RecognizerStatus, Speaker, VoiceEvent } from './types';

export const PENDING_MS = 15_000;
/** Transcripts arriving this long after the speaker finished are still its echo. */
const ECHO_MS = 400;

interface PendingConfirm {
  kind: 'confirm';
  action: Action;
  item?: Item;
  lang: Lang;
  until: number;
}
interface PendingItem {
  kind: 'item';
  action: Action;
  lang: Lang;
  until: number;
}

export interface SessionOptions {
  registry: CommandRegistry;
  recognizer: Recognizer;
  speaker: Speaker;
  /** The language to answer in when the transcript does not tell. */
  language: () => Lang;
  onEvent?: (event: VoiceEvent) => void;
  now?: () => number;
}

export class VoiceSession {
  private stopListening: (() => void) | undefined;
  private pending: PendingConfirm | PendingItem | undefined;
  private speakingUntil = 0;
  private readonly now: () => number;

  constructor(private readonly o: SessionOptions) {
    this.now = o.now ?? (() => Date.now());
  }

  get listening(): boolean {
    return !!this.stopListening;
  }

  start(): void {
    if (this.stopListening) return;
    const lang = this.o.language();
    this.stopListening = this.o.recognizer.listen(
      (text, heardLang) => this.hear(text, heardLang),
      (reason) => this.fail(reason),
      (status) => this.status(status),
    );
    this.emit({ kind: 'listening', text: message(lang, 'listening'), lang });
  }

  stop(): void {
    if (!this.stopListening) return;
    this.stopListening();
    this.stopListening = undefined;
    this.pending = undefined;
    this.o.speaker.stop();
    const lang = this.o.language();
    this.emit({ kind: 'stopped', text: message(lang, 'stopped'), lang });
  }

  toggle(): void {
    if (this.stopListening) this.stop();
    else this.start();
  }

  /** One transcript, as the recognizer heard it. Public so tests and tools can speak. */
  hear(transcript: string, heardLang?: Lang): void {
    const text = transcript.trim();
    if (!text || this.now() < this.speakingUntil) return;
    const understood = this.o.registry.grammar.understand(text);
    const lang = heardLang ?? understood?.lang ?? this.o.language();
    this.emit({ kind: 'heard', text, lang });
    this.expirePending(lang);

    if (this.pending?.kind === 'confirm') {
      const p = this.pending;
      if (understood?.intent === 'yes') {
        this.pending = undefined;
        return this.run(p.action, lang, p.item);
      }
      if (understood?.intent === 'no') {
        this.pending = undefined;
        return this.say(message(lang, 'cancelled'), lang);
      }
      // Anything else is a new request; the question lapses.
      this.pending = undefined;
    }

    if (this.pending?.kind === 'item') {
      const p = this.pending;
      const item = understood?.item ?? this.o.registry.grammar.itemOnly(text);
      if (item && (!understood || understood.intent === p.action.id || !this.o.registry.action(understood.intent))) {
        this.pending = undefined;
        return this.request(p.action, lang, item);
      }
      this.pending = undefined;
    }

    // Nothing matched: the recognizer's guess at the language of a mumble
    // means little, so the answer comes in the language the page is read in.
    if (!understood) return this.say(message(this.o.language(), 'notUnderstood'), this.o.language());
    switch (understood.intent) {
      case 'help':
        return this.say(this.o.registry.help(lang), lang);
      case 'yes':
      case 'no':
        return this.say(message(lang, 'nothingPending'), lang);
    }
    const action = this.o.registry.action(understood.intent);
    if (!action) return this.say(message(lang, 'notUnderstood'), lang);
    if (understood.needsItem) {
      this.pending = { kind: 'item', action, lang, until: this.now() + PENDING_MS };
      const names = (action.items?.() ?? []).map((i) => i.label[lang]);
      return this.say(pick(action.whichItem ?? { es: message('es', 'whichItem', { items: listOf('es', names) }), en: message('en', 'whichItem', { items: listOf('en', names) }) }, lang), lang);
    }
    this.request(action, lang, understood.item);
  }

  /** Run the action, or ask first when it changes something that matters. */
  private request(action: Action, lang: Lang, item?: Item): void {
    const blocked = action.blocked?.();
    if (blocked) return this.say(pick(blocked, lang), lang);
    if (action.risk === 'confirm') {
      this.pending = { kind: 'confirm', action, item, lang, until: this.now() + PENDING_MS };
      const subject = item?.label[lang] ?? pick(action.subject?.() ?? '', lang);
      const question = action.confirm ? pick(action.confirm, lang).replace('{item}', subject).replace(/\s+([?.!])/g, '$1') : action.label[lang];
      return this.say(`${question} ${message(lang, 'confirmSuffix')}`, lang);
    }
    this.run(action, lang, item);
  }

  private run(action: Action, lang: Lang, item?: Item): void {
    const outcome = action.run({ item, lang });
    const speech = typeof outcome === 'object' && 'speech' in outcome ? outcome.speech : outcome;
    this.say(pick(speech, lang), lang);
  }

  private expirePending(lang: Lang): void {
    if (this.pending && this.now() > this.pending.until) {
      this.pending = undefined;
      this.emit({ kind: 'said', text: message(lang, 'expired'), lang });
    }
  }

  private say(text: string, lang: Lang): void {
    this.emit({ kind: 'said', text, lang });
    // Until the speaker is done, and a moment after, the microphone hears
    // it. A speaker that never reports the end (a browser voice can) must
    // not leave the session deaf: the window is at most what the sentence
    // would take to say, generously.
    const estimate = Math.max(2_000, text.length * 90);
    const spokenBy = this.now() + estimate + ECHO_MS;
    this.speakingUntil = spokenBy;
    void this.o.speaker
      .say(text, lang)
      .catch(() => undefined)
      .finally(() => {
        this.speakingUntil = Math.min(spokenBy, this.now() + ECHO_MS);
      });
  }

  private status(status: RecognizerStatus): void {
    const lang = this.o.language();
    const text =
      status.kind === 'loading'
        ? message(lang, 'loadingModel', { percent: String(status.percent) })
        : status.kind === 'ready'
          ? message(lang, 'listening')
          : status.kind === 'speech-start'
            ? message(lang, 'hearing')
            : '';
    this.emit({ kind: 'status', text, lang, status });
  }

  private fail(reason: RecognizerFailure): void {
    this.stopListening = undefined;
    this.pending = undefined;
    const lang = this.o.language();
    const key = { unsupported: 'errorUnsupported', microphone: 'errorMicrophone', network: 'errorNetwork', model: 'errorModel' } as const;
    this.emit({ kind: 'error', text: message(lang, key[reason]), lang, reason });
  }

  private emit(event: VoiceEvent): void {
    this.o.onEvent?.(event);
  }
}
