import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DiagnosticQuestionForm } from '../../src/components/DiagnosticQuestionForm'
import { apiClient } from '../../src/api/client'
import { ApiError } from '../../src/api/errors'

// PI-06-VF-04 regression: DiagnosticQuestionForm.handleSubmit previously
// never reset status to 'ready' on the success path, only in the catch
// block -- so a component instance reused across question changes stayed
// permanently disabled after the first successful submission. This suite
// confirms the fix at both layers the repair instruction requires: the
// component's own state-reset behavior, and (in navigation.test.ts /
// e-pgdr-multiple-questions.spec.ts) the caller now keying by question_id.

describe('DiagnosticQuestionForm', () => {
  beforeEach(() => {
    vi.spyOn(apiClient, 'submitAnswer')
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('disables the form while submitting, then returns to usable state on success', async () => {
    let resolveSubmit: (value: unknown) => void = () => {}
    vi.mocked(apiClient.submitAnswer).mockReturnValue(
      new Promise((resolve) => {
        resolveSubmit = resolve
      }) as ReturnType<typeof apiClient.submitAnswer>,
    )
    const onAnswered = vi.fn()

    render(
      <DiagnosticQuestionForm
        caseId="case-1"
        executionId="exec-1"
        question={{ question_id: 'q1', prompt: 'Does the noise happen at idle?', choices: ['yes', 'no'] }}
        onAnswered={onAnswered}
      />,
    )

    fireEvent.change(screen.getByLabelText('Does the noise happen at idle?'), { target: { value: 'yes' } })
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }))

    // Genuinely submitting: form disabled.
    expect(screen.getByLabelText('Does the noise happen at idle?')).toBeDisabled()

    resolveSubmit({
      outcome: 'BLOCKED',
      case_id: 'case-1',
      execution_id: 'exec-1',
      blocked: true,
      terminal: false,
      pending_questions: [{ question_id: 'q2', prompt: 'next' }],
      artifact_id: null,
    })
    await screen.findByRole('button', { name: 'Submit answer' })

    expect(onAnswered).toHaveBeenCalledTimes(1)
    // The critical VF-04 assertion: the form's own internal state resets
    // to usable on the SUCCESS path, not only on failure.
    expect(screen.getByRole('button', { name: 'Submit answer' })).toBeEnabled()
  })

  it('returns to usable state on failure too (already-correct path, unaffected by the fix)', async () => {
    vi.mocked(apiClient.submitAnswer).mockRejectedValue(new ApiError('PGDR_TECHNICAL_FAILURE', 'x', 502))
    render(
      <DiagnosticQuestionForm
        caseId="case-1"
        executionId="exec-1"
        question={{ question_id: 'q1', prompt: 'Free text question' }}
        onAnswered={vi.fn()}
      />,
    )
    fireEvent.change(screen.getByLabelText('Free text question'), { target: { value: 'yes' } })
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }))
    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'Submit answer' })).toBeEnabled()
  })

  it('a fresh instance for a new question (keyed by question_id by the caller) always mounts enabled', () => {
    const { unmount } = render(
      <DiagnosticQuestionForm
        key="q1"
        caseId="case-1"
        executionId="exec-1"
        question={{ question_id: 'q1', prompt: 'Question one' }}
        onAnswered={vi.fn()}
      />,
    )
    unmount()
    render(
      <DiagnosticQuestionForm
        key="q2"
        caseId="case-1"
        executionId="exec-1"
        question={{ question_id: 'q2', prompt: 'Question two' }}
        onAnswered={vi.fn()}
      />,
    )
    expect(screen.getByLabelText('Question two')).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Submit answer' })).toBeEnabled()
  })
})
