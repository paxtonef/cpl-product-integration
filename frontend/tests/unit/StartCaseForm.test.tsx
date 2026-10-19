import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const startCaseVIR = vi.fn()
vi.mock('../../src/api/client', () => ({ apiClient: { startCaseVIR: (...args: unknown[]) => startCaseVIR(...args) } }))

import { StartCaseForm } from '../../src/routes/Registration'

const CONSENT = 'I agree that my VIN or registration number is sent to the vehicle-data providers to identify my vehicle'

// VIR V1 requires the registration country chosen by the user, for a VIN as
// for a plate, and never falls back to France. A plate or a VIN is sent only
// with the user's explicit consent to the external lookup (never pre-ticked).
function renderForm() {
  render(
    <MemoryRouter>
      <StartCaseForm contactId="contact-1" assetId="asset-1" />
    </MemoryRouter>,
  )
}

describe('StartCaseForm registration country', () => {
  beforeEach(() => {
    startCaseVIR.mockReset()
    startCaseVIR.mockResolvedValue({ outcome: 'SUCCESS', case_id: 'case-1' })
  })

  it('refuses to start without an explicit country, even with a VIN', () => {
    renderForm()
    fireEvent.change(screen.getByLabelText('VIN', { exact: true }), { target: { value: 'VF3XXXXXXXXXXXXXX' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/registration country/i)
    expect(startCaseVIR).not.toHaveBeenCalled()
  })

  it('offers no preselected country', () => {
    renderForm()
    expect((screen.getByLabelText('Registration country') as HTMLSelectElement).value).toBe('')
  })

  it('sends the chosen country with a VIN', async () => {
    renderForm()
    fireEvent.change(screen.getByLabelText('VIN', { exact: true }), { target: { value: 'VF3XXXXXXXXXXXXXX' } })
    fireEvent.change(screen.getByLabelText('Registration country'), { target: { value: 'FR' } })
    fireEvent.click(screen.getByLabelText(CONSENT))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(startCaseVIR).toHaveBeenCalledTimes(1))
    expect(startCaseVIR.mock.calls[0][0]).toMatchObject({ vin: 'VF3XXXXXXXXXXXXXX', registration_country_code: 'FR' })
  })

  it('sends the chosen country with a plate', async () => {
    renderForm()
    fireEvent.change(screen.getByLabelText("Registration number (if you don't have the VIN)"), { target: { value: 'AM-BIG-01' } })
    fireEvent.change(screen.getByLabelText('Registration country'), { target: { value: 'FR' } })
    fireEvent.click(screen.getByLabelText(CONSENT))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(startCaseVIR).toHaveBeenCalledTimes(1))
    expect(startCaseVIR.mock.calls[0][0]).toMatchObject({ registration_number: 'AM-BIG-01', registration_country_code: 'FR' })
  })
})

describe('StartCaseForm consent to the external lookup', () => {
  beforeEach(() => {
    startCaseVIR.mockReset()
    startCaseVIR.mockResolvedValue({ outcome: 'SUCCESS', case_id: 'case-1' })
  })

  it('is never pre-ticked', () => {
    renderForm()
    expect(screen.getByLabelText(CONSENT)).not.toBeChecked()
  })

  it('sends nothing without it', () => {
    renderForm()
    fireEvent.change(screen.getByLabelText('VIN', { exact: true }), { target: { value: 'VF3XXXXXXXXXXXXXX' } })
    fireEvent.change(screen.getByLabelText('Registration country'), { target: { value: 'FR' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/consent/i)
    expect(startCaseVIR).not.toHaveBeenCalled()
  })

  it('is sent as given', async () => {
    renderForm()
    fireEvent.change(screen.getByLabelText('VIN', { exact: true }), { target: { value: 'VF3XXXXXXXXXXXXXX' } })
    fireEvent.change(screen.getByLabelText('Registration country'), { target: { value: 'FR' } })
    fireEvent.click(screen.getByLabelText(CONSENT))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(startCaseVIR).toHaveBeenCalledTimes(1))
    expect(startCaseVIR.mock.calls[0][0].consent).toEqual({ external_lookup_allowed: true })
  })
})
