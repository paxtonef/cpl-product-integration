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

  it('says an identification VIR no longer keeps is not kept, never a temporary failure (bloc 3B)', () => {
    render(<ErrorBanner error={new ApiError('VIR_RESULT_NOT_KEPT', 'raw backend detail', 410)} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(/no longer kept/i)
    expect(alert).toHaveTextContent(/confirmed results are not affected/i)
    expect(alert).not.toHaveTextContent(/temporarily unavailable/i)
  })

  it('says a photo past its conservation period is no longer kept (conservation)', () => {
    render(<ErrorBanner error={new ApiError('MEDIA_NOT_KEPT', 'raw backend detail', 410)} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(/photo is no longer kept/i)
    expect(alert).not.toHaveTextContent(/raw backend detail|something went wrong/i)
  })
})
