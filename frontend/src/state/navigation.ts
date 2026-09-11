// Pure navigation model (structuring §6) — given persisted Case state, which
// screen should be shown. No side effects, no API calls — this is what
// JourneyShell consults after fetching real state. Kept pure and separate
// specifically so it is independently unit-testable (structuring §22 /
// build instruction §30).
import type { CaseStatusResponse } from '../api/types'

export type JourneyScreen =
  | 'case-hub'
  | 'clarification'
  | 'diagnostic-question'
  | 'result'
  | 'unknown'

export function decideScreen(caseStatus: CaseStatusResponse, hasPgdrExecution: boolean): JourneyScreen {
  switch (caseStatus.case_status) {
    case 'OPEN':
      return 'case-hub'
    case 'WAITING_FOR_EXTERNAL_INFORMATION':
      return 'clarification'
    case 'IN_PROGRESS':
      // VIR is admissible; the user has not yet started (or has not yet
      // resumed) a PGDR diagnostic. The case hub shows the VIR result and
      // a "start diagnostic" action -- it does not auto-navigate the user
      // into the complaint form, since starting a real PGDR session is a
      // deliberate user action, not something a refresh should trigger.
      return hasPgdrExecution ? 'diagnostic-question' : 'case-hub'
    case 'WAITING_FOR_USER':
      return 'diagnostic-question'
    case 'RESOLVED':
      return 'result'
    default:
      return 'unknown'
  }
}
