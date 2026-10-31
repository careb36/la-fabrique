/**
 * Voice as an alternative to the hands: a few short commands, in English or
 * Spanish, for a person who cannot or prefers not to pinch. The browser's
 * speech recognition does the listening where it exists; where it does not,
 * the Voice button is not shown.
 *
 * `parseCommand` is pure: a transcript in, a command (or nothing) out.
 */

export type Command =
  | { kind: 'approve' }
  | { kind: 'reject' }
  | { kind: 'pause' }
  | { kind: 'resume' }
  | { kind: 'restart' }
  | { kind: 'recenter' }
  | { kind: 'launch'; taskId: string };

interface TaskWords {
  id: string;
  title: string;
}

/** Words that never pick a task: they are in every title or say nothing. */
const STOP = new Set(['a', 'an', 'the', 'of', 'and', 'el', 'la', 'de', 'una', 'un', 'tarea', 'task']);

const words = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9 ]/g, ' ')
    .split(/\s+/)
    .filter(Boolean);

const has = (said: string[], ...phrases: string[]) =>
  phrases.some((p) => {
    const w = words(p);
    return said.some((_, i) => w.every((x, j) => said[i + j] === x));
  });

/**
 * The command in a transcript, or undefined. Launch needs a word of the
 * task's title ("launch the CSV export"), or a first/second/third.
 */
export function parseCommand(transcript: string, tasks: TaskWords[]): Command | undefined {
  const said = words(transcript);
  if (!said.length) return undefined;
  // A send back is checked first: "don't approve it, send it back" must
  // never approve.
  if (has(said, 'send back', 'send it back', 'reject', 'rework', 'devolver', 'devolverla', 'rechazar')) return { kind: 'reject' };
  if (has(said, 'approve', 'ship it', 'ship', 'accept', 'aprobar', 'aprobada', 'aprueba')) return { kind: 'approve' };
  if (has(said, 'resume', 'continue', 'go on', 'seguir', 'continuar', 'reanudar')) return { kind: 'resume' };
  if (has(said, 'pause', 'stop', 'wait', 'pausa', 'pausar', 'espera')) return { kind: 'pause' };
  if (has(said, 'restart', 'start over', 'reiniciar', 'de nuevo')) return { kind: 'restart' };
  if (has(said, 'recenter', 'center', 'come here', 'centrar', 'recentrar')) return { kind: 'recenter' };
  if (has(said, 'launch', 'start', 'run', 'lanzar', 'lanza', 'empezar', 'iniciar')) {
    const ordinal = ['first', 'second', 'third', 'primera', 'segunda', 'tercera'];
    const n = ordinal.findIndex((o) => said.includes(o));
    if (n >= 0 && tasks[n % 3]) return { kind: 'launch', taskId: tasks[n % 3].id };
    const hit = tasks.find((t) => words(t.title).some((w) => !STOP.has(w) && w.length > 1 && said.includes(w)));
    if (hit) return { kind: 'launch', taskId: hit.id };
  }
  return undefined;
}

interface Recognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>; resultIndex: number }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
}

type RecognitionCtor = new () => Recognition;

/** The browser's speech recognition, when it has one. */
export function speechSupported(): boolean {
  const w = globalThis as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return !!(w.SpeechRecognition ?? w.webkitSpeechRecognition);
}

/**
 * Listen until stopped, handing every final transcript to `heard`. The
 * browser ends a session on silence; it is restarted while listening.
 * Returns a function that stops listening.
 */
export function listen(heard: (transcript: string) => void, failed: (why: string) => void): () => void {
  const w = globalThis as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) {
    failed('This browser has no speech recognition.');
    return () => {};
  }
  const rec = new Ctor();
  rec.continuous = true;
  rec.interimResults = false;
  rec.lang = navigator.language || 'en-US';
  let on = true;
  rec.onresult = (e) => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) heard(e.results[i][0].transcript);
    }
  };
  rec.onerror = (e) => {
    // No permission, or no network for the browser's recognizer: stop and say so.
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed' || e.error === 'network') {
      on = false;
      failed(e.error === 'network' ? 'Voice needs a network connection.' : 'Voice needs the microphone.');
    }
  };
  rec.onend = () => {
    if (on) rec.start();
  };
  rec.start();
  return () => {
    on = false;
    rec.stop();
  };
}
