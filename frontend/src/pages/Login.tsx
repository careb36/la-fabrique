import { FormEvent, useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../services/api'
import { useAuthStore } from '../store/useAuthStore'
import { safeReturnPath } from '../lib/returnPath'

export default function Login() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const login = useAuthStore(state => state.login)
  const token = useAuthStore(state => state.token)
  const expiresAt = useAuthStore(state => state.expiresAt)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const from = searchParams.get('from')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(email, password)
      navigate(safeReturnPath(from), { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError(t('auth.notConfigured', {
          defaultValue: 'Authentication is not configured on this server.',
        }))
      } else if (err instanceof ApiError && err.status === 401) {
        setError(t('auth.invalidCredentials', {
          defaultValue: 'Invalid email or password.',
        }))
      } else {
        setError(err instanceof Error ? err.message : t('auth.loginError', {
          defaultValue: 'Unable to log in. Please try again.',
        }))
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (token && expiresAt && expiresAt > Date.now() && !submitting) {
    return <Navigate to={safeReturnPath(from)} replace />
  }

  return (
    <div className="page-container max-w-md">
      <h1 className="text-2xl font-bold text-white mb-6">
        {t('auth.loginTitle', { defaultValue: 'Log in' })}
      </h1>
      {searchParams.get('registered') === 'true' && (
        <p role="status" className="text-green-300 mb-4">
          {t('auth.registerSuccess', { defaultValue: 'Account created. You can now log in.' })}
        </p>
      )}
      <form onSubmit={handleSubmit} className="space-y-4">
        <label className="block text-sm text-gray-300">
          {t('auth.email', { defaultValue: 'Email' })}
          <input
            className="input mt-1 w-full"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={event => setEmail(event.target.value)}
          />
        </label>
        <label className="block text-sm text-gray-300">
          {t('auth.password', { defaultValue: 'Password' })}
          <input
            className="input mt-1 w-full"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={event => setPassword(event.target.value)}
          />
        </label>
        {error && <p role="alert" className="text-red-300">{error}</p>}
        <button className="btn-primary w-full" type="submit" disabled={submitting}>
          {submitting
            ? t('auth.loggingIn', { defaultValue: 'Logging in…' })
            : t('auth.loginTitle', { defaultValue: 'Log in' })}
        </button>
      </form>
      <p className="text-sm text-gray-400 mt-5">
        {t('auth.noAccount', { defaultValue: "Don't have an account?" })}{' '}
        <Link className="text-brand-300" to="/register">
          {t('auth.registerLink', { defaultValue: 'Register' })}
        </Link>
      </p>
    </div>
  )
}
