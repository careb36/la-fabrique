import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './lib/queryClient'
import App from './App'
import { adoptHandoff } from './lib/handoff'
import './styles/index.css'
import './i18n'

// Render once a launcher handoff (if any) has been redeemed, so the app does
// not first send the person to the login screen.
void adoptHandoff().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </React.StrictMode>
  )
})
