import { FormEvent, useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../services/api'
import { useAuthStore } from '../store/useAuthStore'
import { safeReturnPath } from '../lib/returnPath'

export default function Register() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = useAuthStore(state => state.token)
  const expiresAt = useAuthStore(state => state.expiresAt)
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await api.register({ email, full_name: fullName, password })
      navigate('/login?registered=true', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError && err.status === 400
        ? t('auth.emailExists', { defaultValue: 'An account with this email already exists.' })
        : err instanceof Error ? err.message : t('auth.registerError', {
          defaultValue: 'Unable to register. Please try again.',
        }))
    } finally {
      setSubmitting(false)
    }
  }

  if (token && expiresAt && expiresAt > Date.now()) {
    return <Navigate to={safeReturnPath(searchParams.get('from'))} replace />
  }

  return (
    <div className="page-container max-w-md">
      <h1 className="text-2xl font-bold text-white mb-6">
        {t('auth.registerTitle', { defaultValue: 'Create an account' })}
      </h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <label className="block text-sm text-gray-300">
          {t('auth.fullName', { defaultValue: 'Full name' })}
          <input
            className="input mt-1 w-full"
            type="text"
            autoComplete="name"
            required
            value={fullName}
            onChange={event => setFullName(event.target.value)}
          />
        </label>
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
            autoComplete="new-password"
            required
            value={password}
            onChange={event => setPassword(event.target.value)}
          />
        </label>
        {error && <p role="alert" className="text-red-300">{error}</p>}
        <button className="btn-primary w-full" type="submit" disabled={submitting}>
          {t('auth.registerTitle', { defaultValue: 'Create an account' })}
        </button>
      </form>
      <p className="text-sm text-gray-400 mt-5">
        {t('auth.haveAccount', { defaultValue: 'Already have an account?' })}{' '}
        <Link className="text-brand-300" to="/login">
          {t('auth.loginTitle', { defaultValue: 'Log in' })}
        </Link>
      </p>
    </div>
  )
}
