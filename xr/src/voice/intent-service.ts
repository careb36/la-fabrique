/**
 * The understanding tier a model provides, through the speech service's
 * `/v1/intent`: free speech the grammar did not catch, matched to one of
 * the registry's actions by a model that sees the catalogue and nothing
 * else. Its answer is checked here again against the registry (the
 * service already did), and it never runs anything: the session still
 * confirms what matters.
 */

import type { CommandRegistry } from './registry';
import type { SpeechService } from './speech-service';
import { BUILTIN_INTENTS, type Lang, type Understanding } from './types';

export interface IntentResolver {
  (transcript: string, lang: Lang): Promise<Understanding | undefined>;
}

export interface IntentServiceOptions {
  service: SpeechService;
  registry: CommandRegistry;
  /** A line about the application, for the model ("La Fabrique XR, a control room for agents"). */
  context?: string;
}

/** A resolver that asks the speech service, for `VoiceSession`'s `intent` option. */
export function intentResolver(o: IntentServiceOptions): IntentResolver {
  return async (transcript, lang) => {
    const actions = o.registry.actions.map((a) => ({
      id: a.id,
      label: a.label[lang],
      description: a.confirm ? (lang === 'es' ? 'pide confirmación' : 'asks for confirmation') : '',
      items: (a.items?.() ?? []).map((i) => ({ id: i.id, label: i.label[lang] })),
    }));
    const doFetch = o.service.fetch ?? fetch;
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (o.service.apiKey) headers['X-API-Key'] = o.service.apiKey;
    const response = await doFetch(`${o.service.url.replace(/\/+$/, '')}/v1/intent`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ transcript, language: lang, actions, context: o.context ?? '' }),
    });
    if (!response.ok) throw new Error(`speech service answered ${response.status}`);
    const body = (await response.json()) as { intent: string | null; item: string | null; reply: string | null };
    return fromAnswer(body, o.registry, lang);
  };
}

/** The service's answer as an understanding, or undefined when it named nothing the registry has. */
export function fromAnswer(
  answer: { intent: string | null; item: string | null; reply: string | null },
  registry: CommandRegistry,
  lang: Lang,
): Understanding | undefined {
  const reply = answer.reply?.trim() || undefined;
  if (!answer.intent) return reply ? { intent: 'none', lang, reply } : undefined;
  if ((BUILTIN_INTENTS as readonly string[]).includes(answer.intent)) return { intent: answer.intent, lang, reply };
  const action = registry.action(answer.intent);
  if (!action) return reply ? { intent: 'none', lang, reply } : undefined;
  if (!action.items) return { intent: action.id, lang, reply };
  const item = action.items().find((i) => i.id === answer.item);
  return item ? { intent: action.id, lang, item, reply } : { intent: action.id, lang, needsItem: true, reply };
}
