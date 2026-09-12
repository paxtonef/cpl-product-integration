import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { GaragePreparationReport } from '../api/types'
import { ErrorBanner } from '../components/ErrorBanner'
import { GaragePreparationReportView } from '../components/GaragePreparationReportView'
import { JourneyShell } from '../components/JourneyShell'

function ResultReport({ executionId }: { executionId: string }) {
  const [report, setReport] = useState<GaragePreparationReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    apiClient
      .getArtifact(executionId)
      .then((artifact) => setReport(artifact.payload as unknown as GaragePreparationReport))
      .catch((err) => setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500)))
  }, [executionId])

  if (error) return <ErrorBanner error={error} />
  if (!report) {
    return (
      <div role="status" aria-busy="true">
        Loading result…
      </div>
    )
  }
  return <GaragePreparationReportView report={report} />
}

export function Result() {
  const { caseId } = useParams<{ caseId: string }>()
  if (!caseId) return null

  return (
    <JourneyShell caseId={caseId} expectedScreens={['result']}>
      {(state) => {
        const latestPgdr = [...state.history.executions].reverse().find((e) => e.runner_type === 'PGDR')
        if (!latestPgdr) {
          return <ErrorBanner error={new ApiError('NOT_FOUND', 'No diagnostic result found for this case.', 404)} />
        }
        return <ResultReport executionId={latestPgdr.execution_id} />
      }}
    </JourneyShell>
  )
}
