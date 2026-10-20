import { Link, useParams } from 'react-router-dom'
import { JourneyShell } from '../components/JourneyShell'
import { NoticeParcoursLauncher } from '../components/NoticeParcoursLauncher'
import { LEGACY_DIALOGUE } from '../state/legacyDialogue'
import { VIRResultView } from '../components/VIRResultView'

export function CaseHub() {
  const { caseId } = useParams<{ caseId: string }>()
  if (!caseId) return null

  return (
    // Without the legacy dialogue, a case it left behind (questions pending, refusal) stays on this page.
    <JourneyShell caseId={caseId} expectedScreens={LEGACY_DIALOGUE ? ['case-hub'] : ['case-hub', 'diagnostic-question', 'refusal']}>
      {(state) => (
        <main>
          <h1>Vehicle identity resolved</h1>
          <p>Case status: {state.caseStatus.case_status}</p>
          <VIRResultView caseId={caseId} />
          <NoticeParcoursLauncher caseId={caseId} />
          {LEGACY_DIALOGUE && (
            <p>
              <Link to={`/cases/${caseId}/diagnostic`}>Start a diagnostic</Link>
            </p>
          )}
          <p>
            <Link to={`/cases/${caseId}/history`}>View case history</Link>
          </p>
        </main>
      )}
    </JourneyShell>
  )
}
