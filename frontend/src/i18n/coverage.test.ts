import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import en from './en.json'
import es from './es.json'

const SRC_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// Matches `t('key')`, `t("key")` and `i18n.t('key')` whose first argument is a
// plain string literal followed by `,` or `)`. Dynamic keys (template literals,
// variables, concatenation) are intentionally skipped: they cannot be resolved
// statically, so this test does not cover them.
const T_CALL = /(?:(?<![\w$.])|(?<=\bi18n\.))t\(\s*(['"])((?:\\.|(?!\1)[^\\\n])+)\1\s*[,)]/g

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.(ts|tsx)$/.test(entry.name)) return []
    return [path]
  })
}

function usedKeys(): Map<string, string[]> {
  const keys = new Map<string, string[]>()
  for (const file of sourceFiles(SRC_DIR)) {
    const source = readFileSync(file, 'utf8')
    for (const match of source.matchAll(T_CALL)) {
      const key = match[2]
      const files = keys.get(key) ?? []
      files.push(relative(SRC_DIR, file))
      keys.set(key, files)
    }
  }
  return keys
}

function resolvesToString(resource: Record<string, unknown>, key: string): boolean {
  let node: unknown = resource
  for (const part of key.split('.')) {
    if (typeof node !== 'object' || node === null || !(part in node)) return false
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === 'string'
}

function hasTranslation(resource: Record<string, unknown>, key: string): boolean {
  // i18next resolves `key` through `key_one` / `key_other` when `count` is passed.
  return resolvesToString(resource, key) || resolvesToString(resource, `${key}_other`)
}

describe('translation key coverage', () => {
  const keys = usedKeys()

  it('finds statically referenced translation keys in the source', () => {
    expect(keys.size).toBeGreaterThan(0)
  })

  it('defines every statically referenced key in both English and Spanish', () => {
    const resources = { en, es } as Record<string, Record<string, unknown>>
    const missing: Record<string, string[]> = {}
    for (const [lang, resource] of Object.entries(resources)) {
      const absent = [...keys.keys()].filter(key => !hasTranslation(resource, key)).sort()
      if (absent.length) {
        missing[lang] = absent.map(key => `${key}  (${[...new Set(keys.get(key))].join(', ')})`)
      }
    }
    const report = Object.entries(missing)
      .map(([lang, list]) => `${lang}.json is missing ${list.length} key(s):\n  ${list.join('\n  ')}`)
      .join('\n\n')
    expect(missing, report).toEqual({})
  })
})
