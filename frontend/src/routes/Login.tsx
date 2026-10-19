import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import { ErrorBanner } from '../components/ErrorBanner'

// Accounts are created by the operator (no self-registration, no default
// account). Every failed sign-in shows the same message.
export function Login() {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [status, setStatus] = useState<'ready' | 'submitting'>('ready')
  const [error, setError] = useState<ApiError | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from
  // Back to the page that asked for a session (a path of this app only).
  const target = from && from.startsWith('/') && !from.startsWith('//') && from !== '/login' ? from : '/'

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setStatus('submitting')
    try {
      await apiClient.login(login.trim(), password)
      setPassword('')
      navigate(target, { replace: true })
    } catch (err) {
      setPassword('')
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
      setStatus('ready')
    }
  }

  return (
    <main>
      <form onSubmit={handleSubmit} aria-label="Sign in">
        <h1>Sign in</h1>
        {error && <ErrorBanner error={error} />}
        <div>
          <label htmlFor="login">Login</label>
          <input id="login" autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} disabled={status === 'submitting'} />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={status === 'submitting'}
          />
        </div>
        <button type="submit" disabled={status === 'submitting' || !login.trim() || !password}>
          {status === 'submitting' ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
