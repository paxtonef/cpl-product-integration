import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../src/api/client'
import { ApiError } from '../../src/api/errors'
import { AccountPassword } from '../../src/routes/AccountPassword'

function LoginStub() {
  const location = useLocation()
  return <p>Login page: {(location.state as { message?: string } | null)?.message}</p>
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/account/password']}>
      <Routes>
        <Route path="/account/password" element={<AccountPassword />} />
        <Route path="/login" element={<LoginStub />} />
      </Routes>
    </MemoryRouter>,
  )
}

function fill(current: string, next: string, again: string) {
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: current } })
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: next } })
  fireEvent.change(screen.getByLabelText('New password (again)'), { target: { value: again } })
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
}

describe('AccountPassword', () => {
  beforeEach(() => {
    vi.spyOn(apiClient, 'changePassword')
  })
  afterEach(() => vi.restoreAllMocks())

  it('masks every password field', () => {
    renderPage()
    for (const label of ['Current password', 'New password', 'New password (again)']) {
      expect(screen.getByLabelText(label)).toHaveAttribute('type', 'password')
    }
  })

  it('refuses two different new passwords without calling the server', () => {
    renderPage()
    fill('current-password-1', 'new-password-123', 'new-password-456')
    expect(screen.getByRole('alert')).toHaveTextContent(/do not match/i)
    expect(apiClient.changePassword).not.toHaveBeenCalled()
  })

  it('changes the password and sends the user back to sign in', async () => {
    vi.mocked(apiClient.changePassword).mockResolvedValue(undefined)
    renderPage()
    fill('current-password-1', 'new-password-123', 'new-password-123')
    await waitFor(() => expect(screen.getByText(/Login page/)).toBeInTheDocument())
    expect(apiClient.changePassword).toHaveBeenCalledWith('current-password-1', 'new-password-123')
    expect(screen.getByText(/password has been changed/i)).toBeInTheDocument()
  })

  it('shows the refusal and clears the fields', async () => {
    vi.mocked(apiClient.changePassword).mockRejectedValue(
      new ApiError('PASSWORD_CHANGE_REFUSED', 'current password incorrect, or too many attempts: try again later', 400),
    )
    renderPage()
    fill('wrong-password-1', 'new-password-123', 'new-password-123')
    expect(await screen.findByRole('alert')).toHaveTextContent(/current password is incorrect, or there were too many attempts/i)
    expect(screen.getByLabelText('Current password')).toHaveValue('')
    expect(screen.getByLabelText('New password')).toHaveValue('')
  })

  it('shows the policy message given by the server', async () => {
    vi.mocked(apiClient.changePassword).mockRejectedValue(
      new ApiError('PASSWORD_POLICY', 'password must contain at least 12 characters', 422),
    )
    renderPage()
    fill('current-password-1', 'short', 'short')
    expect(await screen.findByRole('alert')).toHaveTextContent('password must contain at least 12 characters')
  })
})
