import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../src/api/client'
import { ApiError } from '../../src/api/errors'
import { Login } from '../../src/routes/Login'

function renderLogin() {
  render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<p>Home page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

function signIn(password: string) {
  fireEvent.change(screen.getByLabelText('Login'), { target: { value: 'alice' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('Login', () => {
  beforeEach(() => {
    vi.spyOn(apiClient, 'login')
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('masks the password and signs in', async () => {
    vi.mocked(apiClient.login).mockResolvedValue({ csrf_token: 't', contact_id: 'c', account_id: 'a' })
    renderLogin()
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
    signIn('a-long-password')
    await waitFor(() => expect(screen.getByText('Home page')).toBeInTheDocument())
    expect(apiClient.login).toHaveBeenCalledWith('alice', 'a-long-password')
  })

  it('shows one generic message on failure and clears the password', async () => {
    vi.mocked(apiClient.login).mockRejectedValue(new ApiError('AUTHENTICATION_REQUIRED', 'invalid login or password', 401))
    renderLogin()
    signIn('wrong-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid login or password.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
  })
})
