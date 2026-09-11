import { Link } from 'react-router-dom'
import type { CaseHistoryResponse } from '../api/types'

export function CaseHistoryView({ history }: { history: CaseHistoryResponse }) {
  return (
    <section aria-label="Case history">
      <h1>Case history</h1>
      <p>Case status: {history.case_status}</p>
      <ul>
        {history.executions.map((execution) => (
          <li key={execution.execution_id}>
            {execution.runner_type} — {execution.execution_status}
            {execution.artifact_id && (
              <>
                {' '}
                (<Link to={`/cases/${history.case_id}/result`}>view result</Link>)
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
