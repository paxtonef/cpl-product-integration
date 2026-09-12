// Pure navigation model (structuring §6) — given persisted Case state, which
// screen should be shown. No side effects, no API calls — this is what
// JourneyShell consults after fetching real state. Kept pure and separate
// specifically so it is independently unit-testable (structuring §22 /
// build instruction §30).
//
// PI-06-VF-05 repair: independent verification established the *actual*
// backend semantics by direct query against real PI-05/CPL, not by reading
// the case_status name and guessing what it means:
//   - a genuine VIR clarification case (AMBIGUOUS + real clarification
//     questions) stays case_status "IN_PROGRESS" -- clarification
//     availability is a property of the VIR resolution itself, not of the
//     Case's own status string, and must be checked separately.
//   - case_status "WAITING_FOR_EXTERNAL_INFORMATION" is set ONLY after a
//     genuine PI-02 refusal (register_vir_resolution_result never sets it;
//     only PI-04's _sync_case_with_execution does, at diagnostics-start
//     time, when PI-02 refuses the handoff).
// The original mapping had these two backwards. This repair derives the
// screen from the combination the real API actually provides, per the
// repair instruction's own §8 guidance -- no new backend field invented.
import type { CaseStatusResponse } from '../api/types'

export type JourneyScreen =
  | 'case-hub'
  | 'clarification'
  | 'refusal'
  | 'diagnostic-question'
  | 'result'
  | 'unknown'

export function decideScreen(
  caseStatus: CaseStatusResponse,
  hasPgdrExecution: boolean,
  clarificationAvailable: boolean,
): JourneyScreen {
  switch (caseStatus.case_status) {
    case 'OPEN':
      return 'case-hub'
    case 'WAITING_FOR_EXTERNAL_INFORMATION':
      // Set only after a real PI-02 refusal (confirmed against the real
      // backend) -- never a clarification-needed signal.
      return 'refusal'
    case 'IN_PROGRESS':
      // VIR is admissible (or ambiguous-with-questions); the user has not
      // yet started (or has not yet resumed) a PGDR diagnostic.
      if (hasPgdrExecution) return 'diagnostic-question'
      if (clarificationAvailable) return 'clarification'
      // The case hub shows the VIR result and a "start diagnostic" action
      // -- it does not auto-navigate the user into the complaint form,
      // since starting a real PGDR session is a deliberate user action,
      // not something a refresh should trigger.
      return 'case-hub'
    case 'WAITING_FOR_USER':
      return 'diagnostic-question'
    case 'RESOLVED':
      return 'result'
    default:
      return 'unknown'
  }
}
