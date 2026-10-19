import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import { ErrorBanner } from '../components/ErrorBanner'
import { RegistrationForm, type RegistrationResult } from '../components/RegistrationForm'
import { VIRResolutionPanel } from '../components/VIRResolutionPanel'
import type { CaseVIRResponse } from '../api/types'

// VIR V1 resolves only for a registration country chosen explicitly by the
// user (VIR's countries.yaml: France is the only enabled one); never preselected
// nor deduced here.
const REGISTRATION_COUNTRIES = [{ code: 'FR', label: 'France' }]

export function StartCaseForm({ contactId, assetId }: { contactId: string; assetId: string }) {
  const [vin, setVin] = useState('')
  const [registrationNumber, setRegistrationNumber] = useState('')
  const [registrationCountry, setRegistrationCountry] = useState('')
  const [consent, setConsent] = useState(false)
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
    if (!registrationCountry) {
      setError(new ApiError('VALIDATION', 'Please choose the registration country.', 422))
      return
    }
    if (!consent) {
      setError(new ApiError('VALIDATION', 'Your consent is needed before your VIN or registration number is looked up.', 422))
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
        registration_country_code: registrationCountry,
        consent: { external_lookup_allowed: consent },
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
      <div>
        <label htmlFor="registrationCountry">Registration country</label>
        <select
          id="registrationCountry"
          value={registrationCountry}
          onChange={(event) => setRegistrationCountry(event.target.value)}
          disabled={status === 'submitting'}
        >
          <option value="" disabled>
            Choose…
          </option>
          {REGISTRATION_COUNTRIES.map((country) => (
            <option key={country.code} value={country.code}>
              {country.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <input
          id="externalLookupConsent"
          type="checkbox"
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
          disabled={status === 'submitting'}
        />
        <label htmlFor="externalLookupConsent">
          I agree that my VIN or registration number is sent to the vehicle-data providers to identify my vehicle
        </label>
        <p>Nothing is looked up without this consent; the number is sent only for this lookup.</p>
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
