import { describe, expect, it } from 'vitest'
import { decideScreen } from '../../src/state/navigation'
import type { CaseStatusResponse } from '../../src/api/types'

function caseStatus(status: string): CaseStatusResponse {
  return { case_id: 'case-1', case_status: status }
}

describe('decideScreen', () => {
  it('routes OPEN to case-hub', () => {
    expect(decideScreen(caseStatus('OPEN'), false)).toBe('case-hub')
  })

  it('routes WAITING_FOR_EXTERNAL_INFORMATION to clarification', () => {
    expect(decideScreen(caseStatus('WAITING_FOR_EXTERNAL_INFORMATION'), false)).toBe('clarification')
  })

  it('routes IN_PROGRESS with no PGDR execution to case-hub, not auto-starting a diagnostic', () => {
    expect(decideScreen(caseStatus('IN_PROGRESS'), false)).toBe('case-hub')
  })

  it('routes IN_PROGRESS with a PGDR execution already present to diagnostic-question', () => {
    expect(decideScreen(caseStatus('IN_PROGRESS'), true)).toBe('diagnostic-question')
  })

  it('routes WAITING_FOR_USER to diagnostic-question regardless of the hasPgdrExecution flag', () => {
    expect(decideScreen(caseStatus('WAITING_FOR_USER'), false)).toBe('diagnostic-question')
    expect(decideScreen(caseStatus('WAITING_FOR_USER'), true)).toBe('diagnostic-question')
  })

  it('routes RESOLVED to result', () => {
    expect(decideScreen(caseStatus('RESOLVED'), true)).toBe('result')
  })

  it('routes an unrecognized status to unknown rather than guessing', () => {
    expect(decideScreen(caseStatus('CLOSED'), false)).toBe('unknown')
    expect(decideScreen(caseStatus('CANCELLED'), false)).toBe('unknown')
    expect(decideScreen(caseStatus('REOPENED'), false)).toBe('unknown')
  })
})
