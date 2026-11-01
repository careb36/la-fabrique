/**
 * voice: a bilingual voice-control layer for an application.
 *
 * An application declares its actions in a `CommandRegistry`; a
 * `VoiceSession` listens through a `Recognizer`, understands with the
 * registry's `Grammar`, confirms what matters and talks back through a
 * `Speaker`. Nothing in this folder imports from outside it, so the layer
 * can move to its own package unchanged.
 */

export { Grammar, guessLang, resolveItem, type IntentSpec } from './grammar';
export { listOf, message, MESSAGES, pick, type MessageKey } from './messages';
export { firstAvailable, recognitionLanguage, WebSpeechRecognizer } from './recognizer';
export { CommandRegistry } from './registry';
export { PENDING_MS, VoiceSession, type SessionOptions } from './session';
export { chooseVoice, FallbackSpeaker, SilentSpeaker, WebSpeechSpeaker } from './speaker';
export { compile, indexOf, nameWords, STOP_WORDS, words } from './text';
export * from './types';
