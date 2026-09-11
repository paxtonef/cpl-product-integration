import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ComplaintForm } from '../components/ComplaintForm'
import { DiagnosticQuestionForm } from '../components/DiagnosticQuestionForm'
import { ErrorBanner } from '../components/ErrorBanner'
import { JourneyShell } from '../components/JourneyShell'
import { RefusalPanel } from '../components/RefusalPanel'
import type { DiagnosticResponse } from '../api/types'
import { ApiError } from '../api/errors'

function DiagnosticInner({ caseId }: { caseId: string }) {
  const [current, setCurrent] = useState<DiagnosticResponse | null>(null)
  const navigate = useNavigate()

  function handleResult(result: DiagnosticResponse) {
    if (result.outcome === 'COMPLETED') {
      navigate(`/cases/${caseId}/result`)
      return
    }
    setCurrent(result)
  }

  if (current?.outcome === 'PI02_HANDOFF_REFUSED') {
    return <RefusalPanel detail={current.detail} />
  }

  if (current?.blocked && current.execution_id && current.pending_questions.length > 0) {
    return (
      <DiagnosticQuestionForm
        caseId={caseId}
        executionId={current.execution_id}
        question={current.pending_questions[0]}
        onAnswered={handleResult}
      />
    )
  }

  return <ComplaintForm caseId={caseId} onStarted={handleResult} />
}

export function Diagnostic() {
  const { caseId } = useParams<{ caseId: string }>()
  if (!caseId) return null

  return (
    <JourneyShell caseId={caseId} expectedScreens={['case-hub', 'diagnostic-question']}>
      {(state) => {
        if (!state.currentPgdrExecutionId) {
          return (
            <main>
              <DiagnosticInner caseId={caseId} />
            </main>
          )
        }
        return (
          <main>
            <DiagnosticQuestionRecovery caseId={caseId} executionId={state.currentPgdrExecutionId} />
          </main>
        )
      }}
    </JourneyShell>
  )
}

function DiagnosticQuestionRecovery({ caseId, executionId }: { caseId: string; executionId: string }) {
  const [error] = useState<ApiError | null>(null)
  const navigate = useNavigate()

  function handleResult(result: DiagnosticResponse) {
    if (result.outcome === 'COMPLETED') {
      navigate(`/cases/${caseId}/result`)
      return
    }
    if (result.pending_questions.length > 0) {
      navigate(0)
    }
  }

  if (error) return <ErrorBanner error={error} />

  return (
    <div>
      <p>Your diagnostic is waiting for an answer. If you know the answer to the last question you were
        asked, you can retry submitting it below; otherwise this session may no longer be resumable in this
        browser session (a known limitation — please contact support if so).</p>
      <DiagnosticQuestionForm
        caseId={caseId}
        executionId={executionId}
        question={{ question_id: '', prompt: 'Re-enter your last answer' }}
        onAnswered={handleResult}
      />
    </div>
  )
}
