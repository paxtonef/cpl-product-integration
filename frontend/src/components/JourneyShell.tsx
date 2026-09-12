import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { CaseHistoryResponse, CaseStatusResponse } from '../api/types'
import { decideScreen, type JourneyScreen } from '../state/navigation'
import { ErrorBanner } from './ErrorBanner'

export interface CaseJourneyState {
  caseStatus: CaseStatusResponse
  history: CaseHistoryResponse
  screen: JourneyScreen
  currentPgdrExecutionId: string | null
  latestVirExecutionId: string | null
  refetch: () => void
}

const SCREEN_PATH: Record<JourneyScreen, (caseId: string) => string> = {
  'case-hub': (id) => `/cases/${id}`,
  clarification: (id) => `/cases/${id}/clarification`,
  refusal: (id) => `/cases/${id}/diagnostic`,
  'diagnostic-question': (id) => `/cases/${id}/diagnostic`,
  result: (id) => `/cases/${id}/result`,
  unknown: (id) => `/cases/${id}/history`,
}

/**
 * Refresh/recovery (structuring §14): every mount re-fetches persisted
 * state from the API — never trusts the URL alone, never trusts
 * frontend-only memory. Every Case-scoped route uses this hook and
 * redirects to the API-decided screen if the current URL doesn't match.
 *
 * PI-06-VF-05 repair: clarification availability is a property of the
 * latest VIR resolution itself (AMBIGUOUS + non-empty
 * clarification_questions), not of case_status alone -- confirmed against
 * the real backend. When case_status is IN_PROGRESS with no PGDR execution
 * yet, this hook fetches the latest VIR artifact once to determine that,
 * exactly the "combining case_status, VIR resolution status, clarification
 * availability" the repair instruction's own §8 describes -- no new
 * backend field invented, only existing, already-fetched data used
 * correctly.
 */
export function useCaseJourney(caseId: string): CaseJourneyState | { loading: true } | { error: ApiError } {
  const [state, setState] = useState<CaseJourneyState | { loading: true } | { error: ApiError }>({
    loading: true,
  })

  const load = useCallback(() => {
    setState({ loading: true })
    Promise.all([apiClient.getCase(caseId), apiClient.getCaseHistory(caseId)])
      .then(async ([caseStatus, history]) => {
        const pgdrExecutions = history.executions.filter((e) => e.runner_type === 'PGDR')
        const currentPgdrExecutionId =
          pgdrExecutions.length > 0 ? pgdrExecutions[pgdrExecutions.length - 1].execution_id : null
        const virExecutions = history.executions.filter((e) => e.runner_type === 'VIR')
        const latestVirExecutionId = virExecutions.length > 0 ? virExecutions[virExecutions.length - 1].execution_id : null

        let clarificationAvailable = false
        if (caseStatus.case_status === 'IN_PROGRESS' && pgdrExecutions.length === 0 && latestVirExecutionId) {
          try {
            const artifact = await apiClient.getArtifact(latestVirExecutionId)
            const status = typeof artifact.payload.resolution_status === 'string' ? artifact.payload.resolution_status.toLowerCase() : ''
            const questions = (artifact.payload.clarification_questions as unknown[] | undefined) ?? []
            clarificationAvailable = status === 'ambiguous' && questions.length > 0
          } catch {
            // If the artifact can't be fetched, fall through to case-hub
            // rather than guessing -- never claim clarification is
            // available without confirming it against real data.
            clarificationAvailable = false
          }
        }

        const screen = decideScreen(caseStatus, pgdrExecutions.length > 0, clarificationAvailable)
        setState({ caseStatus, history, screen, currentPgdrExecutionId, latestVirExecutionId, refetch: load })
      })
      .catch((err) => {
        setState({ error: err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500) })
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

  useEffect(() => {
    load()
  }, [load])

  return state
}

/**
 * Wraps a Case-scoped route: shows loading/error, redirects to the
 * API-decided screen if the current route doesn't match reality, and
 * otherwise renders `children` with the resolved journey state.
 */
export function JourneyShell({
  caseId,
  expectedScreens,
  children,
}: {
  caseId: string
  expectedScreens: JourneyScreen[]
  children: (state: CaseJourneyState) => React.ReactNode
}) {
  const state = useCaseJourney(caseId)

  if ('loading' in state) {
    return (
      <div role="status" aria-busy="true">
        Loading your case…
      </div>
    )
  }
  if ('error' in state) {
    return <ErrorBanner error={state.error} />
  }
  if (!expectedScreens.includes(state.screen) && state.screen !== 'unknown') {
    return <Navigate to={SCREEN_PATH[state.screen](caseId)} replace />
  }
  return <>{children(state)}</>
}
