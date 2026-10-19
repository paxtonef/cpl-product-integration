import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import { ErrorBanner } from '../components/ErrorBanner'

// The signed-in user's own password change: current password required, the
// new one typed twice. On success PI-05 revokes every session of the account
// (this one included), so the user signs in again with the new password.
// Nothing is kept: the fields are cleared after every attempt.
export function AccountPassword() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newPasswordAgain, setNewPasswordAgain] = useState('')
  const [status, setStatus] = useState<'ready' | 'submitting'>('ready')
  const [error, setError] = useState<ApiError | null>(null)
  const navigate = useNavigate()

  function clear() {
    setCurrentPassword('')
    setNewPassword('')
    setNewPasswordAgain('')
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    if (newPassword !== newPasswordAgain) {
      setError(new ApiError('VALIDATION', 'The two new passwords do not match.', 422))
      return
    }
    setStatus('submitting')
    try {
      await apiClient.changePassword(currentPassword, newPassword)
      clear()
      navigate('/login', {
        replace: true,
        state: { message: 'Your password has been changed. Please sign in with your new password.' },
      })
    } catch (err) {
      clear()
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
      setStatus('ready')
    }
  }

  const submitting = status === 'submitting'
  return (
    <main>
      <form onSubmit={handleSubmit} aria-label="Change password">
        <h1>Change password</h1>
        {error && <ErrorBanner error={error} />}
        <div>
          <label htmlFor="currentPassword">Current password</label>
          <input
            id="currentPassword"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            disabled={submitting}
          />
        </div>
        <div>
          <label htmlFor="newPassword">New password</label>
          <input
            id="newPassword"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            disabled={submitting}
          />
        </div>
        <div>
          <label htmlFor="newPasswordAgain">New password (again)</label>
          <input
            id="newPasswordAgain"
            type="password"
            autoComplete="new-password"
            value={newPasswordAgain}
            onChange={(event) => setNewPasswordAgain(event.target.value)}
            disabled={submitting}
          />
        </div>
        <p>You will be signed out everywhere and asked to sign in again with the new password.</p>
        <button type="submit" disabled={submitting || !currentPassword || !newPassword || !newPasswordAgain}>
          {submitting ? 'Changing…' : 'Change password'}
        </button>
      </form>
      <p>
        <Link to="/">Back</Link>
      </p>
    </main>
  )
}
