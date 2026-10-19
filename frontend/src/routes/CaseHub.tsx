import { Link, useParams } from 'react-router-dom'
import { JourneyShell } from '../components/JourneyShell'
import { NoticeParcoursLauncher } from '../components/NoticeParcoursLauncher'
import { VIRResultView } from '../components/VIRResultView'

export function CaseHub() {
  const { caseId } = useParams<{ caseId: string }>()
  if (!caseId) return null

  return (
    <JourneyShell caseId={caseId} expectedScreens={['case-hub']}>
      {(state) => (
        <main>
          <h1>Vehicle identity resolved</h1>
          <p>Case status: {state.caseStatus.case_status}</p>
          <VIRResultView caseId={caseId} />
          <NoticeParcoursLauncher caseId={caseId} />
          <p>
            <Link to={`/cases/${caseId}/diagnostic`}>Start a diagnostic</Link>
          </p>
          <p>
            <Link to={`/cases/${caseId}/history`}>View case history</Link>
          </p>
        </main>
      )}
    </JourneyShell>
  )
}
