/**
 * Whisper, the way this layer uses it: which language, then the words.
 *
 * Shared by the worker that runs in the page and the bench that measures
 * in Node, so the numbers measured are the behaviour shipped. The model,
 * processor and tokenizer are transformers.js objects, typed loosely here
 * so this file depends on none of its imports.
 *
 * - `detectLanguage`: the encoder once, one decoder step from
 *   <|startoftranscript|>, the likeliest among the languages the app
 *   speaks. transformers.js has no detection of its own (an unset language
 *   means English), and among Whisper's ninety-nine languages a one-second
 *   "vení acá" can come out Japanese.
 * - `transcribe`: with the app's vocabulary as the text "said before" the
 *   phrase (<|startofprev|> + hint + the usual start tokens), which steers
 *   the decoding toward the commands; only what follows is decoded.
 */

import type { Lang } from './types';

export interface GenerationConfigLike {
  decoder_start_token_id: number;
  prev_sot_token_id?: number;
  no_timestamps_token_id: number;
  lang_to_id: Record<string, number>;
  task_to_id: Record<string, number>;
}

export interface TokenizerLike {
  encode(text: string, options: { add_special_tokens: boolean }): ArrayLike<number | bigint>;
  decode(ids: number[], options: { skip_special_tokens: boolean }): string;
}

export interface WhisperLike {
  generation_config: GenerationConfigLike;
  (inputs: Record<string, unknown>): Promise<{ logits: { data: ArrayLike<number> } }>;
  generate(options: Record<string, unknown>): Promise<{ tolist(): (number | bigint)[][] }>;
}

export type ProcessorLike = (audio: Float32Array) => Promise<Record<string, unknown>>;
export type TensorCtor = new (type: string, data: BigInt64Array | bigint[], dims: number[]) => unknown;

/** How far ahead (in logits) a language must be to overrule the one the page is read in. */
export const PRIOR_MARGIN = 1.0;

/**
 * The likeliest of `candidates` from the first decoder step's logits. With
 * `preferred` (the language the page is read in), a close call goes to it:
 * a one-word "pausá" is a coin toss for a small model, and the person is
 * more likely speaking the language they chose.
 */
export function pickLanguage(logits: ArrayLike<number>, gc: GenerationConfigLike, candidates: readonly Lang[], preferred?: Lang, margin = PRIOR_MARGIN): Lang {
  let best: Lang = candidates[0];
  let score = -Infinity;
  for (const lang of candidates) {
    const v = logits[gc.lang_to_id[`<|${lang}|>`]];
    if (v > score) {
      score = v;
      best = lang;
    }
  }
  if (preferred && preferred !== best && candidates.includes(preferred)) {
    const own = logits[gc.lang_to_id[`<|${preferred}|>`]];
    if (score - own < margin) return preferred;
  }
  return best;
}

export async function detectLanguage(
  model: WhisperLike,
  processor: ProcessorLike,
  Tensor: TensorCtor,
  audio: Float32Array,
  candidates: readonly Lang[],
  preferred?: Lang,
): Promise<Lang> {
  const gc = model.generation_config;
  const inputs = await processor(audio);
  const out = await model({ ...inputs, decoder_input_ids: new Tensor('int64', [BigInt(gc.decoder_start_token_id)], [1, 1]) });
  return pickLanguage(out.logits.data, gc, candidates, preferred);
}

/** The decoder's first tokens: the hint as previous text, then the usual start. */
export function promptedInitTokens(gc: GenerationConfigLike, tokenizer: TokenizerLike, lang: Lang, hint: string, maxHintTokens = 200): number[] {
  const encode = (text: string): number[] => Array.from(tokenizer.encode(text, { add_special_tokens: false }), Number);
  const hintIds = hint.trim() ? encode(` ${hint.trim()}`).slice(-maxHintTokens) : [];
  const prev = gc.prev_sot_token_id ?? encode('<|startofprev|>')[0];
  return [
    ...(hintIds.length ? [Number(prev), ...hintIds] : []),
    gc.decoder_start_token_id,
    gc.lang_to_id[`<|${lang}|>`],
    gc.task_to_id.transcribe,
    gc.no_timestamps_token_id,
  ];
}

export async function transcribe(
  model: WhisperLike,
  processor: ProcessorLike,
  tokenizer: TokenizerLike,
  audio: Float32Array,
  lang: Lang,
  hint: string,
  maxNewTokens = 60,
): Promise<string> {
  const init = promptedInitTokens(model.generation_config, tokenizer, lang, hint);
  const inputs = await processor(audio);
  const generated = await model.generate({ ...inputs, decoder_input_ids: init, max_new_tokens: maxNewTokens });
  const ids = Array.from(generated.tolist()[0], Number).slice(init.length);
  return tokenizer.decode(ids, { skip_special_tokens: true }).trim();
}
