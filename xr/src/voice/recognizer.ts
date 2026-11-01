/**
 * Recognizers: where transcripts come from.
 *
 * `WebSpeechRecognizer` is the browser's own (Chrome, Edge, the desktop
 * emulator): instant, no download, but absent in the Meta Quest browser and
 * dependent on Google's service. Other recognizers (a model running in the
 * page, the backend's) implement the same `Recognizer` and the session does
 * not know which it got; `firstAvailable` picks the first that works here.
 */

import type { Lang, Recognizer, RecognizerFailure } from './types';

interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>; resultIndex: number }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
}
type RecognitionCtor = new () => SpeechRecognitionLike;

function speechRecognitionCtor(): RecognitionCtor | undefined {
  const w = globalThis as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

/** The BCP-47 tag the browser recognizer is asked for. */
export function recognitionLanguage(lang: Lang): string {
  return lang === 'es' ? 'es-AR' : 'en-US';
}

export class WebSpeechRecognizer implements Recognizer {
  constructor(private readonly language: () => Lang) {}

  available(): boolean {
    return !!speechRecognitionCtor();
  }

  listen(heard: (transcript: string, lang?: Lang) => void, failed: (reason: RecognizerFailure) => void): () => void {
    const Ctor = speechRecognitionCtor();
    if (!Ctor) {
      failed('unsupported');
      return () => {};
    }
    const rec = new Ctor();
    const lang = this.language();
    rec.continuous = true;
    rec.interimResults = false;
    // The browser's recognizer listens in one language at a time; it is the
    // one the person reads the app in, and a phrase in the other language is
    // still often transcribed well enough for the grammar.
    rec.lang = recognitionLanguage(lang);
    let on = true;
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) heard(e.results[i][0].transcript, undefined);
      }
    };
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        on = false;
        failed('microphone');
      } else if (e.error === 'network') {
        on = false;
        failed('network');
      }
    };
    // The browser ends a session on silence; it is restarted while listening.
    rec.onend = () => {
      if (on) rec.start();
    };
    rec.start();
    return () => {
      on = false;
      rec.stop();
    };
  }
}

/** The first recognizer that can work here, or undefined when none can. */
export function firstAvailable<T extends { available(): boolean }>(candidates: T[]): T | undefined {
  return candidates.find((c) => c.available());
}
