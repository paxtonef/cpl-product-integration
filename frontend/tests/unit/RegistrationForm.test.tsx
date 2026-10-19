import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const registerVehicle = vi.fn()
vi.mock('../../src/api/client', () => ({ apiClient: { registerVehicle: (...args: unknown[]) => registerVehicle(...args) } }))

import { RegistrationForm } from '../../src/components/RegistrationForm'

// The vehicle is registered for the signed-in user: the page never names a
// contact (the server fixes it from the session).
describe('RegistrationForm', () => {
  beforeEach(() => {
    registerVehicle.mockReset()
    registerVehicle.mockResolvedValue({ outcome: 'SUCCESS', contact_id: 'c', asset_id: 'a' })
  })

  it('asks for no contact identifier', () => {
    render(<RegistrationForm onSuccess={() => undefined} />)
    expect(screen.queryByLabelText(/contact id/i)).toBeNull()
    expect(screen.queryByLabelText('Your name')).toBeNull()
  })

  it('registers without naming a contact', async () => {
    const onSuccess = vi.fn()
    render(<RegistrationForm onSuccess={onSuccess} />)
    fireEvent.click(screen.getByRole('button', { name: 'Register' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith({ contactId: 'c', assetId: 'a' }))
    const body = registerVehicle.mock.calls[0][0]
    expect(body.existing_contact_id).toBeUndefined()
    expect(body.display_name).toBeUndefined()
  })
})
