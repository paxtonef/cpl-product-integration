import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { ClarificationQuestionPayload } from '../api/types'
import { ClarificationForm } from '../components/ClarificationForm'
import { ErrorBanner } from '../components/ErrorBanner'
import { JourneyShell } from '../components/JourneyShell'

function ClarificationQuestions({ caseId, vetExecutionId }: { caseId: string; vetExecutionId: string }) {
  const [questions, setQuestions] = useState<ClarificationQuestionPayload[] | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    apiClient
      .getArtifact(vetExecutionId)
      .then((artifact) => {
        const raw = (artifact.payload.clarification_questions ?? []) as ClarificationQuestionPayload[]
        setQuestions(raw)
      })
      .catch((err) => setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500)))
  }, [vetExecutionId])

  if (error) return <ErrorBanner error={error} />
  if (!questions) {
    return (
      <div role="status" aria-busy="true">
        Loading…
      </div>
    )
  }
  if (questions.length === 0) {
    return (
      <div role="status">
        <p>We weren't able to resolve your vehicle's identity automatically, and no further clarification is
          currently available. Please try registering again with different information.</p>
      </div>
    )
  }
  return (
    <ClarificationForm caseId={caseId} questions={questions} onSubmitted={() => navigate(0)} />
  )
}

export function Clarification() {
  const { caseId } = useParams<{ caseId: string }>()
  if (!caseId) return null

  return (
    <JourneyShell caseId={caseId} expectedScreens={['clarification']}>
      {(state) => {
        const latestVirExecution = [...state.history.executions].reverse().find((e) => e.runner_type === 'VIR')
        if (!latestVirExecution) {
          return <ErrorBanner error={new ApiError('NOT_FOUND', 'No VIR resolution found for this case.', 404)} />
        }
        return (
          <main>
            <ClarificationQuestions caseId={caseId} vetExecutionId={latestVirExecution.execution_id} />
          </main>
        )
      }}
    </JourneyShell>
  )
}
