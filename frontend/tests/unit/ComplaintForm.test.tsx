import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ComplaintForm } from '../../src/components/ComplaintForm'

// Block 5 (preparation for production): no vision provider is qualified or
// authorised (owner closed the Vision project on 2026-09-30); photo
// analysis is unavailable and the page says so instead of implying it.
describe('ComplaintForm photo analysis', () => {
  it('states that photo analysis is unavailable and offers no photo', () => {
    render(
      <MemoryRouter>
        <ComplaintForm caseId="case-1" onStarted={() => undefined} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('note')).toHaveTextContent('Photo analysis is not available.')
    expect(screen.queryByLabelText(/consent to media analysis/i)).toBeNull()
    expect(document.querySelector('input[type="file"]')).toBeNull()
  })
})
