import { useState } from 'react'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import { ErrorBanner } from './ErrorBanner'

export interface RegistrationResult {
  contactId: string
  assetId: string
}

export function RegistrationForm({ onSuccess }: { onSuccess: (result: RegistrationResult) => void }) {
  const [status, setStatus] = useState<'ready' | 'submitting'>('ready')
  const [error, setError] = useState<ApiError | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setStatus('submitting')
    try {
      const idempotencySeed = crypto.randomUUID()
      const result = await apiClient.registerVehicle({
        contact_idempotency_key: `contact-${idempotencySeed}`,
        asset_idempotency_key: `asset-${idempotencySeed}`,
      })
      if (result.outcome !== 'SUCCESS' || !result.contact_id || !result.asset_id) {
        setError(new ApiError('CONFLICT', result.detail ?? 'Registration could not be completed.', 409))
        setStatus('ready')
        return
      }
      onSuccess({ contactId: result.contact_id, assetId: result.asset_id })
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
      setStatus('ready')
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Vehicle registration">
      <h1>Register your vehicle</h1>
      {error && <ErrorBanner error={error} />}
      <p>The vehicle is registered to your account.</p>
      <button type="submit" disabled={status === 'submitting'}>
        {status === 'submitting' ? 'Registering…' : 'Register'}
      </button>
    </form>
  )
}
