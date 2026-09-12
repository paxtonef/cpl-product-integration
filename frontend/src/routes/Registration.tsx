import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import { ErrorBanner } from '../components/ErrorBanner'
import { RegistrationForm, type RegistrationResult } from '../components/RegistrationForm'
import { VIRResolutionPanel } from '../components/VIRResolutionPanel'
import type { CaseVIRResponse } from '../api/types'

function StartCaseForm({ contactId, assetId }: { contactId: string; assetId: string }) {
  const [vin, setVin] = useState('')
  const [registrationNumber, setRegistrationNumber] = useState('')
  const [status, setStatus] = useState<'ready' | 'submitting'>('ready')
  const [error, setError] = useState<ApiError | null>(null)
  const [result, setResult] = useState<CaseVIRResponse | null>(null)
  const navigate = useNavigate()

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    if (!vin.trim() && !registrationNumber.trim()) {
      setError(new ApiError('VALIDATION', 'Please enter a VIN or a registration number.', 422))
      return
    }
    setStatus('submitting')
    try {
      const response = await apiClient.startCaseVIR({
        contact_id: contactId,
        asset_id: assetId,
        request_id: crypto.randomUUID(),
        vin: vin.trim() || null,
        registration_number: registrationNumber.trim() || null,
        registration_country_code: registrationNumber.trim() ? 'FR' : null,
        consent: { external_lookup_allowed: true },
        case_idempotency_key: crypto.randomUUID(),
      })
      if (!response.case_id) {
        setError(new ApiError('CPL_PERSISTENCE_FAILURE', response.detail ?? 'Could not start your case.', 502))
        setStatus('ready')
        return
      }
      setResult(response)
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
      setStatus('ready')
    }
  }

  if (result?.case_id) {
    return (
      <div>
        <VIRResolutionPanel result={result} />
        <button type="button" onClick={() => navigate(`/cases/${result.case_id}`)}>
          Continue
        </button>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Vehicle identity">
      <h2>Vehicle identity</h2>
      {error && <ErrorBanner error={error} />}
      <div>
        <label htmlFor="vin">VIN</label>
        <input id="vin" value={vin} onChange={(event) => setVin(event.target.value)} disabled={status === 'submitting'} />
      </div>
      <div>
        <label htmlFor="registrationNumber">Registration number (if you don't have the VIN)</label>
        <input
          id="registrationNumber"
          value={registrationNumber}
          onChange={(event) => setRegistrationNumber(event.target.value)}
          disabled={status === 'submitting'}
        />
      </div>
      <button type="submit" disabled={status === 'submitting'}>
        {status === 'submitting' ? 'Starting…' : 'Continue'}
      </button>
    </form>
  )
}

export function Registration() {
  const [registration, setRegistration] = useState<RegistrationResult | null>(null)

  if (!registration) {
    return (
      <main>
        <RegistrationForm onSuccess={setRegistration} />
      </main>
    )
  }
  return (
    <main>
      <StartCaseForm contactId={registration.contactId} assetId={registration.assetId} />
    </main>
  )
}
