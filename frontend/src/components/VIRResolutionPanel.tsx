import type { CaseVIRResponse } from '../api/types'

const ADMISSIBLE_NO_QUESTIONS = new Set([
  'resolved',
  'provisionally_resolved',
  'insufficient_data',
  'contradictory',
])

export function isClarificationRequired(status: string | null | undefined, hasQuestions: boolean): boolean {
  return status?.toLowerCase() === 'ambiguous' && hasQuestions
}

export function VIRResolutionPanel({ result }: { result: CaseVIRResponse }) {
  const status = result.vir_resolution_status?.toLowerCase()
  return (
    <div>
      <h2>Vehicle identity resolution</h2>
      <p>
        Status:{' '}
        <strong>
          {status && ADMISSIBLE_NO_QUESTIONS.has(status) ? 'Resolved' : result.vir_resolution_status}
        </strong>
      </p>
      {result.detail && <p>{result.detail}</p>}
    </div>
  )
}
