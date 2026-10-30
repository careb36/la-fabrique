import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import i18n from 'i18next'
import es from '../i18n/es.json'
import Login from './Login'
import Register from './Register'
import { useAuthStore } from '../store/useAuthStore'
import { useAppStore } from '../store/useAppStore'

const { mockApi, MockApiError } = vi.hoisted(() => {
  class MockApiError extends Error {
    constructor(public status: number, message: string) {
      super(message)
    }
  }
  return {
    MockApiError,
    mockApi: {
      login: vi.fn(),
      register: vi.fn(),
      me: vi.fn(),
    },
  }
})

vi.mock('../services/api', () => ({
  api: mockApi,
  ApiError: MockApiError,
}))

function CurrentPath() {
  const location = useLocation()
  return <output data-testid="current-path">{location.pathname}{location.search}{location.hash}</output>
}

function renderLogin(initialEntry = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/target" element={<CurrentPath />} />
        <Route path="/" element={<CurrentPath />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('login and registration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.getState().logout()
    useAuthStore.setState({ meLoaded: false, loadingMe: false, profileError: null })
    useAppStore.getState().setActiveSprint(null)
  })

  it.each(['/login', '/register'])('redirects signed-in visitors from %s to their safe return path', async path => {
    useAuthStore.setState({ token: 'signed-token', expiresAt: Date.now() + 60_000 })
    renderLogin(`${path}?from=${encodeURIComponent('/target?tab=mine#details')}`)

    expect(await screen.findByTestId('current-path')).toHaveTextContent('/target?tab=mine#details')
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(mockApi.login).not.toHaveBeenCalled()
    expect(mockApi.register).not.toHaveBeenCalled()
  })

  it.each([
    ['/login', undefined],
    ['/register', undefined],
    ['/login', '//example.com'],
    ['/register', '/\\example.com'],
    ['/login', '/register'],
    ['/register', '/login?from=/target'],
    ['/login', '/companies/select'],
  ])('redirects signed-in visitors home from %s with return path %s', async (path, from) => {
    useAuthStore.setState({ token: 'signed-token', expiresAt: Date.now() + 60_000 })
    renderLogin(`${path}${from ? `?from=${encodeURIComponent(from)}` : ''}`)

    expect(await screen.findByTestId('current-path')).toHaveTextContent(/^\/$/)
  })

  it.each(['/login', '/register'])('keeps %s accessible with an expired token', path => {
    useAuthStore.setState({ token: 'expired-token', expiresAt: Date.now() - 1 })
    renderLogin(path)

    expect(screen.getByLabelText('Password')).toBeInTheDocument()
  })

  it('stores the token and profile and navigates to the from destination', async () => {
    mockApi.login.mockResolvedValue({
      access_token: 'signed-token',
      token_type: 'bearer',
      expires_in: 3600,
    })
    mockApi.me.mockResolvedValue({
      user_id: 8,
      email: 'a@example.com',
      full_name: 'Ada Lovelace',
      memberships: [],
    })
    renderLogin('/login?from=%2Ftarget%3Ftab%3Dmine')

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByTestId('current-path')).toHaveTextContent('/target?tab=mine')
    expect(useAuthStore.getState().token).toBe('signed-token')
    expect(useAuthStore.getState().user).toEqual({
      user_id: 8,
      email: 'a@example.com',
      full_name: 'Ada Lovelace',
      support_admin: false,
    })
    expect(mockApi.me).toHaveBeenCalledOnce()
  })

  it('falls back home for a backslash-based cross-origin return path', async () => {
    mockApi.login.mockResolvedValue({
      access_token: 'signed-token',
      token_type: 'bearer',
      expires_in: 3600,
    })
    mockApi.me.mockResolvedValue({
      user_id: 8,
      email: 'a@example.com',
      full_name: 'Ada Lovelace',
      memberships: [],
    })
    renderLogin('/login?from=%2F%5Cexample.com')

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByTestId('current-path')).toHaveTextContent('/')
  })

  it('shows an invalid-credentials error without populating the store', async () => {
    mockApi.login.mockRejectedValue(new MockApiError(401, 'Invalid email or password'))
    renderLogin()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
  })

  it('shows the dedicated not-configured message for a 503', async () => {
    mockApi.login.mockRejectedValue(new MockApiError(503, 'Service is starting up'))
    renderLogin()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Authentication is not configured on this server.',
    )
    expect(screen.getByRole('alert')).not.toHaveTextContent('Service is starting up')
  })

  it('navigates to login after successful registration', async () => {
    mockApi.register.mockResolvedValue({ user_id: 9, email: 'new@example.com' })
    renderLogin('/register')

    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Grace Hopper' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'new@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }))

    await waitFor(() => expect(mockApi.register).toHaveBeenCalledWith({
      email: 'new@example.com',
      full_name: 'Grace Hopper',
      password: 'password',
    }))
    expect(await screen.findByText('Account created. You can now log in.')).toBeInTheDocument()
  })

  it('renders login labels in Spanish', async () => {
    i18n.addResourceBundle('es', 'translation', es, true, true)
    await i18n.changeLanguage('es')
    renderLogin()

    expect(screen.getByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument()
    expect(screen.getByLabelText('Correo electrónico')).toBeInTheDocument()
    expect(screen.getByLabelText('Contraseña')).toBeInTheDocument()
    await i18n.changeLanguage('en')
  })
})
