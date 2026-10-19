import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient, onUnauthenticated } from '../../src/api/client'

// Preparation for production, block 3: the browser holds no secret of its
// own -- the session lives in an HttpOnly cookie the page never reads, and
// every unsafe request carries the CSRF token PI-05 handed out at login.
function jsonResponse(status: number, body: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('apiClient session handling', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('sends the CSRF token from login on unsafe requests, with same-origin credentials', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { csrf_token: 'csrf-1', contact_id: 'c', account_id: 'a' }))
    await apiClient.login('alice', 'a-long-password')
    fetchMock.mockResolvedValueOnce(jsonResponse(201, { outcome: 'SUCCESS', contact_id: 'c', asset_id: 'x' }))
    await apiClient.registerVehicle({ contact_idempotency_key: 'k1', asset_idempotency_key: 'k2' })
    const [, init] = fetchMock.mock.calls[1]
    expect(init.credentials).toBe('same-origin')
    expect(init.headers['X-CSRF-Token']).toBe('csrf-1')
  })

  it('recovers the CSRF token after a reload from GET /auth/session', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { csrf_token: 'csrf-2', contact_id: 'c', account_id: 'a' }))
    await apiClient.restoreSession()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/session')
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { outcome: 'BLOCKED' }))
    await apiClient.submitAnswer('case', 'exec', { question_id: 'q', value: 'v' })
    expect(fetchMock.mock.calls[1][1].headers['X-CSRF-Token']).toBe('csrf-2')
  })

  it('notifies listeners when the session is missing or expired', async () => {
    const listener = vi.fn()
    const unsubscribe = onUnauthenticated(listener)
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { error_category: 'AUTHENTICATION_REQUIRED', message: 'authentication required' }))
    await expect(apiClient.getCase('case-1')).rejects.toMatchObject({ status: 401 })
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  it('forgets the CSRF token on logout', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { csrf_token: 'csrf-3', contact_id: 'c', account_id: 'a' }))
    await apiClient.login('alice', 'a-long-password')
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await apiClient.logout()
    expect(fetchMock.mock.calls[1][1].headers['X-CSRF-Token']).toBe('csrf-3')
    fetchMock.mockResolvedValueOnce(jsonResponse(403, { error_category: 'CSRF_REJECTED', message: 'x' }))
    await expect(apiClient.registerVehicle({ contact_idempotency_key: 'a', asset_idempotency_key: 'b' })).rejects.toBeTruthy()
    expect(fetchMock.mock.calls[2][1].headers['X-CSRF-Token']).toBeUndefined()
  })

  it('offers no contact creation (accounts are created by the operator)', () => {
    expect('createContact' in apiClient).toBe(false)
  })
})
