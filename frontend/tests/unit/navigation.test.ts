import { describe, expect, it } from 'vitest'
import { decideScreen } from '../../src/state/navigation'
import type { CaseStatusResponse } from '../../src/api/types'

function caseStatus(status: string): CaseStatusResponse {
  return { case_id: 'case-1', case_status: status }
}

describe('decideScreen', () => {
  it('routes OPEN to case-hub', () => {
    expect(decideScreen(caseStatus('OPEN'), false, false)).toBe('case-hub')
  })

  // PI-06-VF-05 regression: independent verification established the real
  // backend semantics by direct query against real PI-05/CPL, not by
  // reading the case_status name and guessing what it means.

  it('CASE A -- real VIR clarification: AMBIGUOUS + IN_PROGRESS + questions present -> clarification', () => {
    // Confirmed against the real backend: a genuine AMBIGUOUS-with-
    // clarification-questions VIR resolution leaves case_status
    // "IN_PROGRESS" -- clarification availability is a property of the VIR
    // resolution itself, passed in here as the third argument, never
    // derived from case_status alone.
    expect(decideScreen(caseStatus('IN_PROGRESS'), false, true)).toBe('clarification')
  })

  it('CASE B -- real PI-02 refusal: WAITING_FOR_EXTERNAL_INFORMATION -> refusal, never clarification', () => {
    // Confirmed against the real backend: this status is set ONLY after a
    // genuine PI-02 refusal (PI-04's _sync_case_with_execution, at
    // diagnostics-start time) -- never for a clarification-needed VIR
    // result. The old (wrong) mapping routed this to 'clarification'.
    expect(decideScreen(caseStatus('WAITING_FOR_EXTERNAL_INFORMATION'), false, false)).toBe('refusal')
    // Even if clarificationAvailable were somehow (incorrectly) computed
    // true for such a case, WAITING_FOR_EXTERNAL_INFORMATION's own
    // case_status branch must still win -- refusal is never overridden by
    // a clarification signal.
    expect(decideScreen(caseStatus('WAITING_FOR_EXTERNAL_INFORMATION'), false, true)).toBe('refusal')
  })

  it('routes IN_PROGRESS with no PGDR execution and no clarification available to case-hub, not auto-starting a diagnostic', () => {
    expect(decideScreen(caseStatus('IN_PROGRESS'), false, false)).toBe('case-hub')
  })

  it('routes IN_PROGRESS with a PGDR execution already present to diagnostic-question, even if clarification-available were (incorrectly) true', () => {
    expect(decideScreen(caseStatus('IN_PROGRESS'), true, false)).toBe('diagnostic-question')
    expect(decideScreen(caseStatus('IN_PROGRESS'), true, true)).toBe('diagnostic-question')
  })

  it('routes WAITING_FOR_USER to diagnostic-question regardless of the hasPgdrExecution/clarification flags', () => {
    expect(decideScreen(caseStatus('WAITING_FOR_USER'), false, false)).toBe('diagnostic-question')
    expect(decideScreen(caseStatus('WAITING_FOR_USER'), true, false)).toBe('diagnostic-question')
  })

  it('routes RESOLVED to result', () => {
    expect(decideScreen(caseStatus('RESOLVED'), true, false)).toBe('result')
  })

  it('routes an unrecognized status to unknown rather than guessing', () => {
    expect(decideScreen(caseStatus('CLOSED'), false, false)).toBe('unknown')
    expect(decideScreen(caseStatus('CANCELLED'), false, false)).toBe('unknown')
    expect(decideScreen(caseStatus('REOPENED'), false, false)).toBe('unknown')
  })
})
