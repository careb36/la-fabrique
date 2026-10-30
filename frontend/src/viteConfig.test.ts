// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'

async function loadBase(electron: string | undefined, mode = 'production') {
  vi.resetModules()
  if (electron === undefined) vi.stubEnv('ELECTRON', '')
  else vi.stubEnv('ELECTRON', electron)
  // A computed specifier keeps `tsc` from pulling vite.config.ts (which belongs to
  // tsconfig.node.json) into the app project; Vitest still resolves it at runtime.
  const specifier = '../vite.config.ts'
  const { default: config } = await import(/* @vite-ignore */ specifier)
  const resolved = typeof config === 'function' ? await config({ command: 'build', mode }) : config
  return (resolved as { base?: string }).base
}

describe('vite base path', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('uses absolute asset URLs for the web build, relative ones only for Electron', async () => {
    // With './' a deep link such as /evidence/1 requests /evidence/assets/... and renders blank.
    expect(await loadBase(undefined)).toBe('/')
    // Electron loads dist/index.html from file:// and needs relative URLs.
    expect(await loadBase('1')).toBe('./')
    // `npm run electron:build` selects the Electron base with `--mode electron`.
    expect(await loadBase(undefined, 'electron')).toBe('./')
  })
})
