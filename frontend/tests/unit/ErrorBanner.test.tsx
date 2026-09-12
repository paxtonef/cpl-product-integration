import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ErrorBanner } from '../../src/components/ErrorBanner'
import { ApiError } from '../../src/api/errors'

describe('ErrorBanner', () => {
  it('renders a distinct message per error category', () => {
    render(<ErrorBanner error={new ApiError('PROCESS_LOCAL_STATE_UNAVAILABLE', 'raw backend detail', 409)} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(/can no longer accept an answer/i)
    // never renders raw backend exception text
    expect(alert).not.toHaveTextContent('raw backend detail')
  })

  it('distinguishes BLOCKED-adjacent process-local-state from generic technical failure', () => {
    const { rerender } = render(
      <ErrorBanner error={new ApiError('PGDR_TECHNICAL_FAILURE', 'irrelevant', 502)} />,
    )
    const technicalText = screen.getByRole('alert').textContent
    rerender(<ErrorBanner error={new ApiError('CASE_ORCHESTRATION_FAILURE', 'irrelevant', 502)} />)
    const orchestrationText = screen.getByRole('alert').textContent
    expect(technicalText).not.toEqual(orchestrationText)
  })
})
