import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { afterEach, beforeAll } from 'vitest'
import en from '../i18n/en.json'

beforeAll(async () => {
  if (!i18n.isInitialized) {
    i18n.use(initReactI18next)
    await i18n.init({
      resources: {
        en: {
          translation: en,
        },
      },
      lng: 'en',
      fallbackLng: 'en',
      interpolation: {
        escapeValue: false,
      },
    })
  }
})

afterEach(() => {
  cleanup()
  // Node-environment tests (e.g. the Vite config test) have no localStorage.
  if (typeof localStorage !== 'undefined') localStorage.clear()
})
