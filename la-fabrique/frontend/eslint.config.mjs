// Lint gate for user-facing text: every string shown in JSX goes through
// i18next (CLAUDE.md, "Frontend i18n"), so the Spanish UI never shows English
// literals. Type checking stays with `tsc --noEmit`.
import tseslint from 'typescript-eslint'
import i18next from 'eslint-plugin-i18next'

export default tseslint.config(
  {
    ignores: ['dist/**', 'dist-electron-main/**', 'node_modules/**', 'electron/**'],
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/**/*.test.{ts,tsx}', 'src/test/**'],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { i18next },
    rules: {
      'i18next/no-literal-string': [
        'error',
        {
          // JSX text and the attributes a user reads or hears.
          mode: 'jsx-only',
          'jsx-attributes': {
            include: ['title', 'alt', 'placeholder', 'aria-label', 'aria-description', 'label'],
          },
          words: {
            exclude: [
              // The plugin's defaults: numbers and punctuation, ALL_CAPS
              // codes, HTML entities and emoji.
              '[0-9!-/:-@[-`{-~\\s·•…→←↑↓▾▸▴▲▼✓✔✕✗×–—]+',
              '[A-Z_-]+',
              /^[\p{Extended_Pictographic}\p{Emoji_Component}\uFE0F\u200D\s]+$/u,
              // Brand name, the same in every language.
              'La Fabrique',
              // Hex colours computed inside JSX are never prose. Other value
              // lists (enums, time zones) belong in module constants, outside JSX.
              '#[0-9a-fA-F]{3,8}',
              // Tailwind class lists built inside JSX (`cond ? 'bg-x' : 'bg-y'`).
              /^(?=.*[a-z0-9\]]-[a-z0-9[])[a-z0-9:/[\]#._%()!,-]+(\s+[a-z0-9:/[\]#._%()!,-]+)*$/,
            ],
          },
        },
      ],
    },
  },
)
