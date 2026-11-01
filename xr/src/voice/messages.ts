/**
 * What the layer itself says, in both languages.
 *
 * Written per language, not translated: a sentence that is read out loud
 * has to sound like the language it is in. Spanish is Rioplatense (voseo),
 * like the rest of the product's voice. Applications add nothing here;
 * their sentences come back from their actions.
 */

import type { Lang, Localized } from './types';

const ES = {
  listening: 'Te escucho.',
  hearing: 'Escuchando...',
  loadingModel: 'Cargando el modelo de voz ({percent} %)...',
  stopped: 'Dejé de escuchar.',
  confirmSuffix: 'Decí sí o no.',
  confirmed: 'Hecho.',
  cancelled: 'Cancelado.',
  nothingPending: 'No hay nada que confirmar.',
  notUnderstood: 'No entendí. Decí «ayuda» para oír las órdenes.',
  help: 'Podés decir: {list}.',
  whichItem: '¿Cuál? {items}.',
  expired: 'Pasó el tiempo; no hice nada.',
  errorUnsupported: 'Este navegador no puede escuchar.',
  errorMicrophone: 'Necesito el micrófono para escucharte.',
  errorNetwork: 'La voz necesita conexión en este navegador.',
  errorModel: 'No pude cargar el modelo de voz.',
  or: 'o',
} as const;

const EN: Record<keyof typeof ES, string> = {
  listening: 'Listening.',
  hearing: 'Hearing you...',
  loadingModel: 'Loading the voice model ({percent}%)...',
  stopped: 'Stopped listening.',
  confirmSuffix: 'Say yes or no.',
  confirmed: 'Done.',
  cancelled: 'Cancelled.',
  nothingPending: 'Nothing to confirm.',
  notUnderstood: 'I did not catch that. Say "help" to hear the commands.',
  help: 'You can say: {list}.',
  whichItem: 'Which one? {items}.',
  expired: 'Time ran out; nothing was done.',
  errorUnsupported: 'This browser cannot listen.',
  errorMicrophone: 'I need the microphone to hear you.',
  errorNetwork: 'Voice needs a network connection in this browser.',
  errorModel: 'The voice model could not be loaded.',
  or: 'or',
};

export type MessageKey = keyof typeof ES;

export const MESSAGES: Localized<Record<MessageKey, string>> = { es: ES, en: EN };

export function message(lang: Lang, key: MessageKey, vars: Record<string, string> = {}): string {
  return MESSAGES[lang][key].replace(/\{(\w+)\}/g, (_, name: string) => vars[name] ?? '');
}

/** "a, b or c" in the language's own way. */
export function listOf(lang: Lang, parts: string[]): string {
  if (parts.length <= 1) return parts.join('');
  return `${parts.slice(0, -1).join(', ')} ${MESSAGES[lang].or} ${parts[parts.length - 1]}`;
}

/** One sentence for a person, from a string or a pair. */
export function pick(speech: string | Localized<string>, lang: Lang): string {
  return typeof speech === 'string' ? speech : speech[lang];
}
