import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ClarificationForm } from '../../src/components/ClarificationForm'

describe('ClarificationForm', () => {
  it('blocks submission until all required questions are answered', () => {
    const onSubmitted = vi.fn()
    render(
      <ClarificationForm
        caseId="case-1"
        questions={[{ question_id: 'q1', prompt: 'What is the manufacturer?', required: true }]}
        onSubmitted={onSubmitted}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /submit/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(/answer all required questions/i)
    expect(onSubmitted).not.toHaveBeenCalled()
  })

  it('renders a select when the question provides choices, a text input otherwise', () => {
    render(
      <ClarificationForm
        caseId="case-1"
        questions={[
          { question_id: 'q1', prompt: 'Pick one', choices: [{ value: 'a', label: 'A' }] },
          { question_id: 'q2', prompt: 'Free text' },
        ]}
        onSubmitted={vi.fn()}
      />,
    )
    expect(screen.getByLabelText('Pick one').tagName).toBe('SELECT')
    expect(screen.getByLabelText('Free text').tagName).toBe('INPUT')
  })
})
