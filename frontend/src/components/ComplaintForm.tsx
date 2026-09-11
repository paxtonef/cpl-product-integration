import { useState } from 'react'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { DiagnosticResponse } from '../api/types'
import { ConsentForm, type ConsentValue } from './ConsentForm'
import { ErrorBanner } from './ErrorBanner'

export function ComplaintForm({
  caseId,
  onStarted,
}: {
  caseId: string
  onStarted: (result: DiagnosticResponse, sessionToken: string) => void
}) {
  const [complaint, setComplaint] = useState('')
  const [consent, setConsent] = useState<ConsentValue>({
    mediaAnalysisAllowed: false,
    reportStorageAllowed: false,
  })
  const [status, setStatus] = useState<'ready' | 'submitting'>('ready')
  const [error, setError] = useState<ApiError | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    if (!complaint.trim()) {
      setError(new ApiError('VALIDATION', 'Please describe the problem.', 422))
      return
    }
    setStatus('submitting')
    try {
      const result = await apiClient.startDiagnostic(caseId, {
        complaint_text: complaint,
        consent_media_analysis_allowed: consent.mediaAnalysisAllowed,
        consent_report_storage_allowed: consent.reportStorageAllowed,
      })
      onStarted(result, crypto.randomUUID())
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
      setStatus('ready')
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Describe the problem">
      <h2>Tell us what's wrong</h2>
      {error && <ErrorBanner error={error} />}
      <div>
        <label htmlFor="complaint">What's happening with your vehicle?</label>
        <textarea
          id="complaint"
          value={complaint}
          onChange={(event) => setComplaint(event.target.value)}
          disabled={status === 'submitting'}
          required
        />
      </div>
      <ConsentForm value={consent} onChange={setConsent} disabled={status === 'submitting'} />
      <button type="submit" disabled={status === 'submitting'}>
        {status === 'submitting' ? 'Starting…' : 'Start diagnostic'}
      </button>
    </form>
  )
}
