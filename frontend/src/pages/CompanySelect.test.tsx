import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import CompanySelect from './CompanySelect'
import ProtectedRoute from '../components/ProtectedRoute'
import { queryClient } from '../lib/queryClient'
import { useAuthStore } from '../store/useAuthStore'

function CurrentPath() {
  const location = useLocation()
  return <output data-testid="current-path">{location.pathname}{location.search}{location.hash}</output>
}

function renderRoutes(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <CurrentPath />
      <Routes>
        <Route element={<ProtectedRoute />}>
          <Route path="/companies/select" element={<CompanySelect />} />
          <Route path="/evidence/5" element={<div>Evidence detail</div>} />
          <Route path="/" element={<div>Home</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('company selection return destination', () => {
  beforeEach(() => {
    queryClient.clear()
    useAuthStore.getState().logout()
    useAuthStore.setState({
      token: 'valid-token',
      expiresAt: Date.now() + 60_000,
      meLoaded: true,
      memberships: [
        { company_id: 14, human_role: 'Owner' },
        { company_id: 28, human_role: 'Viewer' },
      ],
    })
  })

  it.each(['/evidence/5', '/evidence/5?tab=checks#result'])(
    'preserves %s through the selection redirect (issue #7)',
    async destination => {
      renderRoutes(destination)
      const company = await screen.findByRole('button', { name: /Company 14.*Owner/ })
      expect(screen.getByTestId('current-path')).toHaveTextContent(
        `/companies/select?from=${encodeURIComponent(destination)}`,
      )

      fireEvent.click(company)

      expect(await screen.findByText('Evidence detail')).toBeInTheDocument()
      expect(screen.getByTestId('current-path').textContent).toBe(destination)
    },
  )

  it.each(['', 'https://example.com', '//example.com', '/\\example.com', '/companies/select'])(
    'falls back to home for an invalid or recursive destination %s',
    async destination => {
      renderRoutes(`/companies/select?from=${encodeURIComponent(destination)}`)
      fireEvent.click(await screen.findByRole('button', { name: /Company 14.*Owner/ }))

      expect(await screen.findByText('Home')).toBeInTheDocument()
      expect(screen.getByTestId('current-path').textContent).toBe('/')
    },
  )

  it('removes cached queries when switching companies', async () => {
    queryClient.setQueryData(['memory', 14, 'auth'], ['company 14 result'])
    renderRoutes('/companies/select')

    fireEvent.click(await screen.findByRole('button', { name: /Company 28.*Viewer/ }))

    expect(queryClient.getQueryData(['memory', 14, 'auth'])).toBeUndefined()
  })
})
