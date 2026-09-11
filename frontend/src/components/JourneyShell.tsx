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
  refetch: () => void
}

const SCREEN_PATH: Record<JourneyScreen, (caseId: string) => string> = {
  'case-hub': (id) => `/cases/${id}`,
  clarification: (id) => `/cases/${id}/clarification`,
  'diagnostic-question': (id) => `/cases/${id}/diagnostic`,
  result: (id) => `/cases/${id}/result`,
  unknown: (id) => `/cases/${id}/history`,
}

/**
 * Refresh/recovery (structuring §14): every mount re-fetches persisted
 * state from the API — never trusts the URL alone, never trusts
 * frontend-only memory. Every Case-scoped route uses this hook and
 * redirects to the API-decided screen if the current URL doesn't match.
 */
export function useCaseJourney(caseId: string): CaseJourneyState | { loading: true } | { error: ApiError } {
  const [state, setState] = useState<CaseJourneyState | { loading: true } | { error: ApiError }>({
    loading: true,
  })

  const load = useCallback(() => {
    setState({ loading: true })
    Promise.all([apiClient.getCase(caseId), apiClient.getCaseHistory(caseId)])
      .then(([caseStatus, history]) => {
        const pgdrExecutions = history.executions.filter((e) => e.runner_type === 'PGDR')
        const currentPgdrExecutionId =
          pgdrExecutions.length > 0 ? pgdrExecutions[pgdrExecutions.length - 1].execution_id : null
        const screen = decideScreen(caseStatus, pgdrExecutions.length > 0)
        setState({ caseStatus, history, screen, currentPgdrExecutionId, refetch: load })
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
