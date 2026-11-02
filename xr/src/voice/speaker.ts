/**
 * Speakers: how the layer talks back.
 *
 * `WebSpeechSpeaker` uses the browser's `speechSynthesis` with a voice of the
 * language spoken; it is absent in the Meta Quest browser. `SilentSpeaker`
 * says nothing and resolves at once, for a page that shows the words
 * instead (the session emits every sentence as an event either way).
 * `FallbackSpeaker` tries a chain in order, so a better voice is used when
 * it is there and the words are never lost when it is not.
 */

import type { Lang, Speaker } from './types';

interface UtteranceLike {
  lang: string;
  voice: { lang: string; name: string } | null;
  rate: number;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}
interface SynthesisLike {
  speak(u: UtteranceLike): void;
  cancel(): void;
  getVoices(): { lang: string; name: string }[];
}

function synthesis(): SynthesisLike | undefined {
  const w = globalThis as unknown as { speechSynthesis?: SynthesisLike; SpeechSynthesisUtterance?: new (text: string) => UtteranceLike };
  return w.speechSynthesis && w.SpeechSynthesisUtterance ? w.speechSynthesis : undefined;
}

const SYNTHESIS_LANGUAGE: Record<Lang, string> = { es: 'es-AR', en: 'en-US' };

/** Among the browser's voices, the one that fits the language best. */
export function chooseVoice<V extends { lang: string }>(voices: V[], lang: Lang): V | undefined {
  const wanted = SYNTHESIS_LANGUAGE[lang].toLowerCase();
  const tag = (v: V) => v.lang.toLowerCase().replace('_', '-');
  return voices.find((v) => tag(v) === wanted) ?? voices.find((v) => tag(v).startsWith(`${lang}-`) || tag(v) === lang);
}

export class WebSpeechSpeaker implements Speaker {
  available(): boolean {
    return !!synthesis();
  }

  say(text: string, lang: Lang): Promise<void> {
    const s = synthesis();
    const w = globalThis as unknown as { SpeechSynthesisUtterance: new (text: string) => UtteranceLike };
    if (!s) return Promise.resolve();
    return new Promise((resolve) => {
      const u = new w.SpeechSynthesisUtterance(text);
      u.lang = SYNTHESIS_LANGUAGE[lang];
      u.voice = chooseVoice(s.getVoices(), lang) ?? null;
      u.rate = 1.05;
      u.onend = () => resolve();
      u.onerror = () => resolve();
      s.speak(u);
    });
  }

  stop(): void {
    synthesis()?.cancel();
  }
}

export class SilentSpeaker implements Speaker {
  available(): boolean {
    return true;
  }
  say(): Promise<void> {
    return Promise.resolve();
  }
  stop(): void {}
}

export class FallbackSpeaker implements Speaker {
  constructor(private readonly chain: Speaker[]) {}

  private current(): Speaker | undefined {
    return this.chain.find((s) => s.available());
  }

  available(): boolean {
    return !!this.current();
  }

  say(text: string, lang: Lang): Promise<void> {
    return this.current()?.say(text, lang) ?? Promise.resolve();
  }

  stop(): void {
    for (const s of this.chain) s.stop();
  }
}
