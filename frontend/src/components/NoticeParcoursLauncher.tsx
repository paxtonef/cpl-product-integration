import { useState } from 'react'
import { apiClient, apiPageUrl } from '../api/client'
import { ApiError } from '../api/errors'
import { ErrorBanner } from './ErrorBanner'

// Opens PGDR's notice parcours (photo, up to 3 proposed images, the complete
// catalogue, the driver's own selection and confirmation, the notice text and
// the Premier Constat) for this case. The parcours page is PGDR's own, served
// through PI for the case owner only; when PGDR opens no parcours (identity
// not established, no notice, applicability not confirmed), its own reason is
// shown and nothing else is assumed.
export function NoticeParcoursLauncher({
  caseId,
  go = (url: string) => window.location.assign(url),
}: {
  caseId: string
  go?: (url: string) => void
}) {
  const [status, setStatus] = useState<'ready' | 'opening'>('ready')
  const [refusal, setRefusal] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  async function open() {
    setError(null)
    setRefusal(null)
    setStatus('opening')
    try {
      const result = await apiClient.openNoticeParcours(caseId)
      if (result.status === 'opened' && result.page) {
        go(apiPageUrl(result.page))
        return
      }
      setRefusal(result.message ?? 'No manufacturer notice can be shown for this vehicle.')
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
    }
    setStatus('ready')
  }

  return (
    <section aria-label="Warning lights">
      <h2>Warning lights</h2>
      <p>
        Compare a warning light with the images of your vehicle's manufacturer notice, then read what the notice
        says. Images proposed from your photo are only an aid: you choose and confirm.
      </p>
      {error && <ErrorBanner error={error} />}
      {refusal && (
        <p role="status" lang="fr" data-testid="notice-refusal">
          {refusal}
        </p>
      )}
      <button type="button" onClick={open} disabled={status === 'opening'}>
        Open the manufacturer notice
      </button>
    </section>
  )
}
