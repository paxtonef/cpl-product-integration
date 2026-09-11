import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { CaseHistoryResponse } from '../api/types'
import { CaseHistoryView } from '../components/CaseHistoryView'
import { ErrorBanner } from '../components/ErrorBanner'

export function History() {
  const { caseId } = useParams<{ caseId: string }>()
  const [history, setHistory] = useState<CaseHistoryResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    if (!caseId) return
    apiClient
      .getCaseHistory(caseId)
      .then(setHistory)
      .catch((err) => setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500)))
  }, [caseId])

  if (!caseId) return null
  if (error) return <ErrorBanner error={error} />
  if (!history) {
    return (
      <div role="status" aria-busy="true">
        Loading history…
      </div>
    )
  }
  return (
    <main>
      <CaseHistoryView history={history} />
    </main>
  )
}
