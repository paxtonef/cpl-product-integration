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
    // PI-06-VF-04 repair: keyed by question_id (the stable identity PI-05
    // actually returns per question, confirmed against DiagnosticQuestionSchema)
    // so React mounts a genuinely fresh component instance for every new
    // question rather than reusing the previous one's stale internal
    // status/disabled state.
    return (
      <DiagnosticQuestionForm
        key={current.pending_questions[0].question_id}
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
    <JourneyShell caseId={caseId} expectedScreens={['case-hub', 'diagnostic-question', 'refusal']}>
      {(state) => {
        if (state.screen === 'refusal') {
          // PI-06-VF-05 repair: case_status WAITING_FOR_EXTERNAL_INFORMATION
          // means PI-02 already refused the handoff (confirmed against the
          // real backend) -- show the truthful refusal state directly,
          // never a clarification form, and never re-attempt the
          // diagnostic start that already produced this result. No
          // per-refusal detail text is retrievable after the fact (no
          // backend endpoint persists it separately -- confirmed; not
          // invented here), so RefusalPanel renders its own truthful
          // generic message.
          return (
            <main>
              <RefusalPanel />
            </main>
          )
        }
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
