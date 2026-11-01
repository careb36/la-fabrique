/**
 * Scores recognizers and the command grammar against the phrase bank.
 *
 * Two numbers, kept apart because they measure different things:
 *
 * - word error rate (WER) of each recognizer's transcript against the phrase
 *   as written: the recognizer alone;
 * - command accuracy: the transcript, through the room's grammar
 *   (`src/commands.ts`, the one shipped), gives the intent and task the
 *   phrase meant. This is what the person experiences, and it moves when
 *   either the recognizer or the grammar improves.
 *
 * Both are reported per language and per voice; a recognizer that is good
 * in English and poor in Spanish is caught here, not by a person in a
 * headset. The misses are listed so the grammar can learn from them.
 *
 *   npx tsx measure.ts --models tiny,base              # transformers.js in Node
 *   npx tsx measure.ts --models base --prompt          # with the room's vocabulary as Whisper's prompt
 *   npx tsx measure.ts --models base --language force  # the phrase's language given
 *   npx tsx measure.ts --external results/fw-large-v3-turbo.jsonl
 *   npx tsx measure.ts --grammar-only                  # the written phrases, no audio
 *   npx tsx measure.ts --prompts                       # write the vocabulary hints for other tools
 *
 * The transformers.js models are the ones the device would run (q8 weights).
 * `--language detect` (the default) finds the language the way the device
 * will: one decoder step, the likeliest of the languages the app speaks.
 * `prior` adds what the device also knows, the language the page is read
 * in (here the phrase's), which wins a close call. `force` gives the
 * recognizer the phrase's own language, an upper bound;
 * `es` or `en` fixes one, which is what a person speaking the other
 * language would get from a page that does not detect. Node's CPU timing is
 * not the headset's, but the ratio between models is.
 */

import { readdirSync, readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { roomRegistry, taskItems, type RoomHandlers } from '../src/commands.ts';
import { padded } from '../src/voice/endpointer.ts';
import { detectLanguage, transcribe } from '../src/voice/whisper-core.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const AUDIO = join(HERE, 'audio');
const RESULTS = join(HERE, 'results');

type Lang = 'es' | 'en';
const LANGS: Lang[] = ['es', 'en'];

interface Phrase {
  id: string;
  lang: Lang;
  text: string;
  intent: string;
  task?: string;
}
interface Bank {
  tasks: { id: string; title: string }[];
  phrases: Phrase[];
}
interface Transcript {
  voice: string;
  id: string;
  text: string;
  /** The language the recognizer decided on, when it did. */
  language?: string;
  seconds?: number;
}
interface Scored extends Transcript {
  lang: Lang;
  expected: string;
  got: string;
  wer: number;
  hit: boolean;
  /** The recognizer's language matched the phrase's (undefined when it gave none). */
  langHit?: boolean;
}

const bank: Bank = JSON.parse(readFileSync(join(HERE, 'phrases.json'), 'utf8'));
const byId = new Map(bank.phrases.map((p) => [p.id, p]));

// The grammar as shipped, with no room behind it: only what it understands matters here.
const noop = () => 'ok';
const handlers: RoomHandlers = {
  approve: noop, reject: noop, restart: noop, next: noop, pause: noop, resume: noop,
  recenter: noop, mute: noop, unmute: noop, launch: noop, status: noop,
};
const registry = roomRegistry(handlers, () => taskItems(bank.tasks));
const { grammar } = registry;


// -- text ------------------------------------------------------------------

export function normalize(text: string): string[] {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9 ]+/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
}

/** Word error rate: edits over reference words (Levenshtein on words). */
export function wordErrorRate(reference: string, hypothesis: string): number {
  const ref = normalize(reference);
  const hyp = normalize(hypothesis);
  if (!ref.length) return hyp.length ? 1 : 0;
  let prev = Array.from({ length: hyp.length + 1 }, (_, j) => j);
  for (let i = 1; i <= ref.length; i++) {
    const cur = [i];
    for (let j = 1; j <= hyp.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ref[i - 1] === hyp[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return Math.min(1, prev[hyp.length] / ref.length);
}

/** What the grammar makes of a transcript, as "intent" or "launch:task". */
export function understood(transcript: string): string {
  const u = grammar.understand(transcript);
  if (!u) return 'none';
  if (u.intent === 'launch') return u.item ? `launch:${u.item.id}` : 'launch:?';
  return u.intent;
}

function expectedOf(p: Phrase): string {
  return p.intent === 'launch' ? `launch:${p.task}` : p.intent;
}

function score(t: Transcript): Scored | undefined {
  const p = byId.get(t.id);
  if (!p) return undefined;
  const expected = expectedOf(p);
  const got = understood(t.text);
  return {
    ...t,
    lang: p.lang,
    expected,
    got,
    wer: wordErrorRate(p.text, t.text),
    hit: got === expected,
    langHit: t.language ? t.language === p.lang : undefined,
  };
}

// -- recognizers ------------------------------------------------------------

interface Recognizer {
  name: string;
  transcripts(): Promise<Transcript[]>;
}

function wavFiles(): { voice: string; id: string; path: string }[] {
  if (!existsSync(AUDIO)) return [];
  return readdirSync(AUDIO, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .flatMap((d) =>
      readdirSync(join(AUDIO, d.name))
        .filter((f) => f.endsWith('.wav'))
        .map((f) => ({ voice: d.name, id: f.replace(/\.wav$/, ''), path: join(AUDIO, d.name, f) })),
    );
}

interface WaveFileLike {
  toBitDepth(depth: string): void;
  toSampleRate(rate: number): void;
  getSamples(interleaved: boolean, type: typeof Float32Array): Float32Array | Float32Array[];
}
type WaveFileCtor = new (bytes: Buffer) => WaveFileLike;

/** 16 kHz mono float samples from a WAV of any rate or width. */
async function samplesOf(path: string): Promise<Float32Array> {
  // wavefile is CommonJS: under tsx the class is the module itself, under node its default.
  const mod = (await import('wavefile')) as unknown as { WaveFile?: WaveFileCtor; default?: { WaveFile: WaveFileCtor } };
  const WaveFile = mod.WaveFile ?? mod.default!.WaveFile;
  const wav = new WaveFile(readFileSync(path));
  wav.toBitDepth('32f');
  wav.toSampleRate(16000);
  const data = wav.getSamples(false, Float32Array) as Float32Array | Float32Array[];
  if (Array.isArray(data)) {
    const mono = new Float32Array(data[0].length);
    for (const ch of data) for (let i = 0; i < mono.length; i++) mono[i] += ch[i] / data.length;
    return mono;
  }
  return data;
}


/** The written phrase as its own transcript: measures the grammar alone. */
const perfectRecognizer: Recognizer = {
  name: 'written',
  async transcripts() {
    return bank.phrases.map((p) => ({ voice: 'text', id: p.id, text: p.text, language: p.lang, seconds: 0 }));
  },
};

function externalRecognizer(file: string): Recognizer {
  return {
    name: file.replace(/^.*\//, '').replace(/\.jsonl$/, ''),
    async transcripts() {
      return readFileSync(file, 'utf8')
        .split('\n')
        .filter(Boolean)
        .map((line) => JSON.parse(line) as Transcript);
    },
  };
}

type LanguageMode = 'detect' | 'prior' | 'force' | Lang;

function transformersRecognizer(size: string, o: TransformersOptions): Recognizer {
  return {
    name: `whisper-${size}-${o.mode}${o.prompt ? '-prompt' : ''}`,
    async transcripts() {
      const { pipeline, Tensor } = await import('@huggingface/transformers');
      const asr = await pipeline('automatic-speech-recognition', `onnx-community/whisper-${size}`, {
        dtype: { encoder_model: 'q8', decoder_model_merged: 'q8' },
      });
      const hints = { es: registry.vocabularyHint('es'), en: registry.vocabularyHint('en') };
      const out: Transcript[] = [];
      const files = wavFiles().slice(0, o.limit ?? Infinity);
      let n = 0;
      for (const f of files) {
        const audio = padded(await samplesOf(f.path));
        const started = performance.now();
        let lang: Lang | undefined;
        // 'prior': detection with the phrase's language as the page's, the common case.
        if (o.mode === 'detect') lang = await detectLanguage(asr.model, asr.processor, Tensor, audio, LANGS);
        else if (o.mode === 'prior') lang = await detectLanguage(asr.model, asr.processor, Tensor, audio, LANGS, byId.get(f.id)?.lang);
        else if (o.mode === 'force') lang = byId.get(f.id)?.lang;
        else lang = o.mode;
        let text = '';
        try {
          text = o.prompt
            ? await transcribe(asr.model, asr.processor, asr.tokenizer, audio, lang ?? 'en', hints[lang ?? 'en'])
            : ((await asr(audio, { language: lang, task: 'transcribe' })) as { text: string }).text.trim();
        } catch (err) {
          // A clip the model has nothing to say about: an empty transcript, scored as a miss.
          process.stderr.write(`${this.name}: ${f.voice}/${f.id}: ${err instanceof Error ? err.message : String(err)}\n`);
        }
        out.push({ voice: f.voice, id: f.id, text, language: lang, seconds: (performance.now() - started) / 1000 });
        if (++n % 50 === 0) process.stderr.write(`${this.name}: ${n}/${files.length}\n`);
      }
      return out;
    },
  };
}

// -- report -----------------------------------------------------------------

function pct(hits: number, total: number): string {
  return total ? `${((100 * hits) / total).toFixed(0)}%` : '–';
}

function mean(values: number[]): number {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
}

function groupBy<T>(items: T[], key: (t: T) => string): Map<string, T[]> {
  const m = new Map<string, T[]>();
  for (const it of items) {
    const k = key(it);
    m.set(k, [...(m.get(k) ?? []), it]);
  }
  return m;
}

function row(label: string, group: Scored[]): string {
  const withLang = group.filter((r) => r.langHit !== undefined);
  const langCol = withLang.length ? pct(withLang.filter((r) => r.langHit).length, withLang.length) : '–';
  return `| ${label} | ${group.length} | ${pct(group.filter((r) => r.hit).length, group.length)} | ${(100 * mean(group.map((r) => r.wer))).toFixed(1)}% | ${langCol} | ${mean(group.map((r) => r.seconds ?? 0)).toFixed(2)} |`;
}

function report(name: string, rows: Scored[]): string {
  const lines: string[] = [`## ${name}`, ''];
  lines.push('| language | phrases | commands right | WER | language right | s/phrase |', '|---|---|---|---|---|---|');
  for (const [lang, group] of [...groupBy(rows, (r) => r.lang)].sort()) lines.push(row(lang, group));
  lines.push(row('all', rows), '');
  const voices = [...groupBy(rows, (r) => r.voice)].sort();
  if (voices.length > 1) {
    lines.push('| voice | commands right | WER |', '|---|---|---|');
    for (const [voice, group] of voices) {
      lines.push(`| ${voice} | ${pct(group.filter((r) => r.hit).length, group.length)} | ${(100 * mean(group.map((r) => r.wer))).toFixed(1)}% |`);
    }
    lines.push('');
  }
  lines.push('| intent | es | en |', '|---|---|---|');
  for (const [intent, group] of [...groupBy(rows, (r) => r.expected)].sort()) {
    const es = group.filter((r) => r.lang === 'es');
    const en = group.filter((r) => r.lang === 'en');
    lines.push(`| ${intent} | ${pct(es.filter((r) => r.hit).length, es.length)} | ${pct(en.filter((r) => r.hit).length, en.length)} |`);
  }
  const misses = rows.filter((r) => !r.hit);
  lines.push('', `Misses: ${misses.length}`, '');
  for (const m of misses.slice(0, 400)) {
    const said = byId.get(m.id)?.text ?? '';
    lines.push(`- ${m.voice}/${m.id}: said “${said}”, heard “${m.text}”${m.language ? ` (${m.language})` : ''}, understood ${m.got} (wanted ${m.expected})`);
  }
  return lines.join('\n');
}

// -- main -------------------------------------------------------------------

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? (process.argv[i + 1] ?? '') : undefined;
}

async function main(): Promise<void> {
  if (process.argv.includes('--prompts')) {
    // The vocabulary hints, for recognizers measured outside Node (the server tier).
    const prompts = { es: registry.vocabularyHint('es'), en: registry.vocabularyHint('en') };
    mkdirSync(RESULTS, { recursive: true });
    writeFileSync(join(RESULTS, 'prompts.json'), JSON.stringify(prompts, null, 2) + '\n');
    console.log(JSON.stringify(prompts, null, 2));
    return;
  }
  const recognizers: Recognizer[] = [];
  if (process.argv.includes('--grammar-only') || (!arg('models') && !arg('external'))) recognizers.push(perfectRecognizer);
  const mode = (arg('language') ?? 'detect') as LanguageMode;
  const prompt = process.argv.includes('--prompt');
  const limit = arg('limit') ? Number(arg('limit')) : undefined;
  for (const size of (arg('models') ?? '').split(',').filter(Boolean)) recognizers.push(transformersRecognizer(size, { mode, prompt, limit }));
  for (const file of (arg('external') ?? '').split(',').filter(Boolean)) recognizers.push(externalRecognizer(file));

  mkdirSync(RESULTS, { recursive: true });
  for (const r of recognizers) {
    const rows = (await r.transcripts()).map(score).filter((s): s is Scored => !!s);
    const text = report(r.name, rows);
    writeFileSync(join(RESULTS, `${r.name}.json`), JSON.stringify(rows, null, 1));
    writeFileSync(join(RESULTS, `${r.name}.md`), text + '\n');
    console.log(text, '\n');
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
