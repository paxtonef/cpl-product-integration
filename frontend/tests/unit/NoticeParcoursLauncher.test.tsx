import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../src/api/client'
import { ApiError } from '../../src/api/errors'
import { NoticeParcoursLauncher } from '../../src/components/NoticeParcoursLauncher'

afterEach(() => vi.restoreAllMocks())

describe('NoticeParcoursLauncher', () => {
  it('goes to the PGDR page served under the API when the parcours is opened', async () => {
    vi.spyOn(apiClient, 'openNoticeParcours').mockResolvedValue({ status: 'opened', page: '/v1?p=V1-abc' })
    const go = vi.fn()
    render(<NoticeParcoursLauncher caseId="case-1" go={go} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open the manufacturer notice' }))
    await waitFor(() => expect(go).toHaveBeenCalledWith('/api/v1?p=V1-abc'))
    expect(apiClient.openNoticeParcours).toHaveBeenCalledWith('case-1')
  })

  it("shows PGDR's own refusal and goes nowhere", async () => {
    vi.spyOn(apiClient, 'openNoticeParcours').mockResolvedValue({
      status: 'vehicle_identity_insufficient', page: null, message: "L'identité du véhicule n'est pas établie par VIR.",
    })
    const go = vi.fn()
    render(<NoticeParcoursLauncher caseId="case-1" go={go} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open the manufacturer notice' }))
    expect(await screen.findByTestId('notice-refusal')).toHaveTextContent("L'identité du véhicule n'est pas établie par VIR.")
    expect(go).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Open the manufacturer notice' })).toBeEnabled()
  })

  it('shows a technical failure without any detail', async () => {
    vi.spyOn(apiClient, 'openNoticeParcours').mockRejectedValue(
      new ApiError('PGDR_TECHNICAL_FAILURE', 'PGDR notice service unavailable', 502),
    )
    const go = vi.fn()
    render(<NoticeParcoursLauncher caseId="case-1" go={go} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open the manufacturer notice' }))
    expect(await screen.findByText('The diagnostic service is temporarily unavailable. Please try again.')).toBeVisible()
    expect(go).not.toHaveBeenCalled()
  })
})
