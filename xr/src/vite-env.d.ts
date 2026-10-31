/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The backend's address; set it at build time to follow a real sprint. */
  readonly VITE_FABRIQUE_API?: string;
}
