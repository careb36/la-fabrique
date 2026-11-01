import { describe, expect, it } from 'vitest';

import { pickLanguage, promptedInitTokens, transcribe, type GenerationConfigLike, type TokenizerLike, type WhisperLike } from './whisper-core';

const gc: GenerationConfigLike = {
  decoder_start_token_id: 50258,
  prev_sot_token_id: 50361,
  no_timestamps_token_id: 50363,
  lang_to_id: { '<|en|>': 50259, '<|es|>': 50262, '<|ja|>': 50266 },
  task_to_id: { transcribe: 50359, translate: 50358 },
};

/** A tokenizer that gives each word a number and reads them back. */
const tokenizer: TokenizerLike = {
  encode: (text) => text.trim().split(/\s+/).map((w) => w.length),
  decode: (ids, { skip_special_tokens }) => ids.filter((id) => !skip_special_tokens || id < 50000).map((id) => `w${id}`).join(' '),
};

describe('pickLanguage', () => {
  it('chooses the likeliest among the candidates only', () => {
    const logits = new Float32Array(50400);
    logits[50266] = 9; // Japanese, not a candidate
    logits[50262] = 3; // Spanish
    logits[50259] = 1; // English
    expect(pickLanguage(logits, gc, ['es', 'en'])).toBe('es');
    expect(pickLanguage(logits, gc, ['en'])).toBe('en');
  });

  it('a close call goes to the language the page is read in; a clear one does not', () => {
    const logits = new Float32Array(50400);
    logits[50262] = 3.0; // Spanish
    logits[50259] = 2.5; // English, close behind
    expect(pickLanguage(logits, gc, ['es', 'en'], 'en')).toBe('en');
    expect(pickLanguage(logits, gc, ['es', 'en'], 'es')).toBe('es');
    expect(pickLanguage(logits, gc, ['es', 'en'])).toBe('es');
    logits[50259] = 0.5; // English far behind
    expect(pickLanguage(logits, gc, ['es', 'en'], 'en')).toBe('es');
  });
});

describe('promptedInitTokens', () => {
  it('puts the hint as previous text before the usual start tokens', () => {
    expect(promptedInitTokens(gc, tokenizer, 'es', 'aprobá devolvela')).toEqual([50361, 6, 9, 50258, 50262, 50359, 50363]);
  });

  it('without a hint, only the start tokens', () => {
    expect(promptedInitTokens(gc, tokenizer, 'en', '  ')).toEqual([50258, 50259, 50359, 50363]);
  });

  it('keeps only the tail of a long hint', () => {
    const hint = Array.from({ length: 300 }, (_, i) => 'x'.repeat((i % 5) + 1)).join(' ');
    const tokens = promptedInitTokens(gc, tokenizer, 'en', hint, 10);
    expect(tokens).toHaveLength(1 + 10 + 4);
  });
});

describe('transcribe', () => {
  it('decodes only what the model added after the prompt', async () => {
    const seen: Record<string, unknown>[] = [];
    const model = Object.assign(
      async () => ({ logits: { data: new Float32Array(0) } }),
      {
        generation_config: gc,
        generate: async (options: Record<string, unknown>) => {
          seen.push(options);
          const init = options.decoder_input_ids as number[];
          return { tolist: () => [[...init, 5, 7, 50257]] };
        },
      },
    ) as unknown as WhisperLike;
    const text = await transcribe(model, async () => ({ input_features: 'f' }), tokenizer, new Float32Array(16000), 'es', 'pausá');
    expect(text).toBe('w5 w7');
    expect(seen[0].input_features).toBe('f');
    expect(seen[0].max_new_tokens).toBe(60);
  });
});
