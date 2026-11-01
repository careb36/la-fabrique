/**
 * The client of the speech service (`speech-service/`): the server tier.
 *
 * `transcribeRemote` sends a phrase (16 kHz float samples) as WAV and gets
 * the words and the language back; `ServerSpeaker` asks for a sentence as
 * WAV (Kokoro) and plays it. Both take the service's address and, when it
 * wants one, its key; both fail loudly, so the session can fall back.
 */

import { playWav } from './piper-speaker';
import type { Lang, Localized, Speaker } from './types';
import { encodeWav } from './wav';

export interface SpeechService {
  url: string;
  apiKey?: string;
  /** For tests: a stand-in for the global fetch. */
  fetch?: typeof fetch;
}

function headers(service: SpeechService, contentType: string): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': contentType };
  if (service.apiKey) h['X-API-Key'] = service.apiKey;
  return h;
}

export interface RemoteTranscript {
  text: string;
  lang: Lang;
  seconds: number;
}

export async function transcribeRemote(
  service: SpeechService,
  samples: Float32Array,
  options: { languages: Lang[]; preferred?: Lang; hint?: string; rate?: number },
): Promise<RemoteTranscript> {
  const q = new URLSearchParams({ languages: options.languages.join(',') });
  if (options.preferred) q.set('preferred', options.preferred);
  if (options.hint) q.set('prompt', options.hint.slice(0, 2000));
  const doFetch = service.fetch ?? fetch;
  const response = await doFetch(`${service.url.replace(/\/+$/, '')}/v1/transcribe?${q}`, {
    method: 'POST',
    headers: headers(service, 'audio/wav'),
    body: encodeWav(samples, options.rate ?? 16_000),
  });
  if (!response.ok) throw new Error(`speech service answered ${response.status}`);
  const body = (await response.json()) as { text: string; language: string; seconds: number };
  return { text: body.text, lang: body.language === 'en' ? 'en' : 'es', seconds: body.seconds };
}

export interface ServerSpeakerOptions {
  service: SpeechService;
  /** Kokoro voice per language; the service's defaults when absent. */
  voices?: Partial<Localized<string>>;
  play?: (wav: ArrayBuffer) => Promise<number>;
  onStatus?: (status: { kind: 'spoken'; lang: Lang; synthesisSeconds: number; audioSeconds: number }) => void;
}

export class ServerSpeaker implements Speaker {
  readonly name = 'speech-service';
  private stopCurrent: (() => void) | undefined;
  private readonly play: (wav: ArrayBuffer) => Promise<number>;

  constructor(private readonly o: ServerSpeakerOptions) {
    this.play = o.play ?? ((wav) => playWav(wav, (stop) => (this.stopCurrent = stop)));
  }

  available(): boolean {
    return !!this.o.service.url && (!!this.o.play || typeof (globalThis as { AudioContext?: unknown }).AudioContext === 'function');
  }

  async say(text: string, lang: Lang): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed) return;
    const started = performance.now();
    const doFetch = this.o.service.fetch ?? fetch;
    const response = await doFetch(`${this.o.service.url.replace(/\/+$/, '')}/v1/speak`, {
      method: 'POST',
      headers: headers(this.o.service, 'application/json'),
      body: JSON.stringify({ text: trimmed, language: lang, voice: this.o.voices?.[lang] || undefined }),
    });
    if (!response.ok) throw new Error(`speech service answered ${response.status}`);
    const wav = await response.arrayBuffer();
    const synthesisSeconds = (performance.now() - started) / 1000;
    const audioSeconds = await this.play(wav);
    this.o.onStatus?.({ kind: 'spoken', lang, synthesisSeconds, audioSeconds });
  }

  stop(): void {
    this.stopCurrent?.();
    this.stopCurrent = undefined;
  }
}
