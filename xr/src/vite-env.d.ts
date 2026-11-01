/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The backend's address; set it at build time to follow a real sprint. */
  readonly VITE_FABRIQUE_API?: string;
  /** The speech service's address (speech-service/): the server tier of the voice. */
  readonly VITE_SPEECH_API?: string;
}
