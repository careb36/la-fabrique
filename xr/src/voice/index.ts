/**
 * voice: a bilingual voice-control layer for an application.
 *
 * An application declares its actions in a `CommandRegistry`; a
 * `VoiceSession` listens through a `Recognizer`, understands with the
 * registry's `Grammar`, confirms what matters and talks back through a
 * `Speaker`. Nothing in this folder imports from outside it, so the layer
 * can move to its own package unchanged.
 */

export { concat, Endpointer, padded, type EndpointerOptions } from './endpointer';
export { Grammar, guessLang, resolveItem, type IntentSpec } from './grammar';
export { fromAnswer, intentResolver, type IntentResolver, type IntentServiceOptions } from './intent-service';
export { MIC_FRAME, MIC_SAMPLE_RATE, microphoneSupported, openMicrophone } from './microphone';
export { PIPER_VOICES, PiperSpeaker, playWav, type PiperSpeakerOptions, type SpeakerStatus } from './piper-speaker';
export { SileroVad, VAD_CONTEXT, VAD_SAMPLE_RATE, VAD_WINDOW } from './silero';
export { ServerSpeaker, transcribeRemote, type RemoteTranscript, type ServerSpeakerOptions, type SpeechService } from './speech-service';
export { encodeWav } from './wav';
export { detectLanguage, pickLanguage, promptedInitTokens, transcribe } from './whisper-core';
export { WHISPER_MODELS, WhisperRecognizer, whisperSize, type WhisperRecognizerOptions, type WhisperSize } from './whisper-recognizer';
export { listOf, message, MESSAGES, pick, type MessageKey } from './messages';
export { firstAvailable, recognitionLanguage, WebSpeechRecognizer } from './recognizer';
export { CommandRegistry } from './registry';
export { PENDING_MS, VoiceSession, type SessionOptions } from './session';
export { chooseVoice, FallbackSpeaker, SilentSpeaker, WebSpeechSpeaker } from './speaker';
export { compile, indexOf, nameWords, STOP_WORDS, words } from './text';
export * from './types';
