// The one bounded typed API-client boundary for PI-05 (structuring §18):
// one method per real PI-05 route. Contact creation is no longer a web
// operation (accounts and their contacts are created by the operator
// command), so createContact is gone; login/logout/session and the user's
// own case list were added with authentication.
import { toApiError } from './errors'
import type {
  ArtifactResponse,
  CaseHistoryResponse,
  CaseListResponse,
  CaseStatusResponse,
  CaseVIRResponse,
  ContactResponse,
  DiagnosticResponse,
  ExecutionStatusResponse,
  RegisterVehicleRequest,
  RegisterVehicleResponse,
  SessionResponse,
  StartCaseRequest,
  StartDiagnosticRequest,
  SubmitAnswerRequest,
  SubmitClarificationRequest,
  VIRResolutionView,
} from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

// The session itself is an HttpOnly cookie this code never sees; the only
// value held here is the CSRF token PI-05 hands out at login (and again on
// GET /auth/session after a reload), sent back on every unsafe request.
let csrfToken: string | null = null
const unauthenticatedListeners = new Set<() => void>()

export function onUnauthenticated(listener: () => void): () => void {
  unauthenticatedListeners.add(listener)
  return () => unauthenticatedListeners.delete(listener)
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken
  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') {
      csrfToken = null
      unauthenticatedListeners.forEach((listener) => listener())
    }
    throw await toApiError(response)
  }
  return response
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  return (await (await send(method, path, body)).json()) as T
}

async function openSession(path: string, body?: unknown): Promise<SessionResponse> {
  const session = await request<SessionResponse>(body === undefined ? 'GET' : 'POST', path, body)
  csrfToken = session.csrf_token
  return session
}

export const apiClient = {
  login: (login: string, password: string) => openSession('/auth/login', { login, password }),
  restoreSession: () => openSession('/auth/session'),
  logout: async () => {
    try {
      await send('POST', '/auth/logout')
    } finally {
      csrfToken = null
    }
  },
  // Every session of the account, this one included, is revoked by PI-05 on
  // success: the token is dropped and the user signs in again.
  changePassword: async (currentPassword: string, newPassword: string): Promise<void> => {
    await send('POST', '/auth/password', { current_password: currentPassword, new_password: newPassword })
    csrfToken = null
  },
  listCases: () => request<CaseListResponse>('GET', '/cases'),
  getContact: (contactId: string) => request<ContactResponse>('GET', `/contacts/${contactId}`),
  registerVehicle: (body: RegisterVehicleRequest) =>
    request<RegisterVehicleResponse>('POST', '/vehicles', body),
  startCaseVIR: (body: StartCaseRequest) => request<CaseVIRResponse>('POST', '/cases', body),
  submitClarification: (caseId: string, body: SubmitClarificationRequest) =>
    request<CaseVIRResponse>('POST', `/cases/${caseId}/vir/clarifications`, body),
  // Reads the stored VIR result again; never a new lookup.
  getCaseVIR: (caseId: string) => request<VIRResolutionView>('GET', `/cases/${caseId}/vir`),
  confirmVIRField: (caseId: string, fieldPath: string, value: unknown) =>
    request<CaseVIRResponse>('POST', `/cases/${caseId}/vir/confirmations`, { field_path: fieldPath, value }),
  correctVIRField: (caseId: string, fieldPath: string, value: unknown) =>
    request<CaseVIRResponse>('PUT', `/cases/${caseId}/vir/confirmations/${encodeURIComponent(fieldPath)}`, { value }),
  withdrawVIRField: (caseId: string, fieldPath: string) =>
    request<CaseVIRResponse>('DELETE', `/cases/${caseId}/vir/confirmations/${encodeURIComponent(fieldPath)}`),
  getCase: (caseId: string) => request<CaseStatusResponse>('GET', `/cases/${caseId}`),
  getCaseHistory: (caseId: string) => request<CaseHistoryResponse>('GET', `/cases/${caseId}/history`),
  startDiagnostic: (caseId: string, body: StartDiagnosticRequest) =>
    request<DiagnosticResponse>('POST', `/cases/${caseId}/diagnostics`, body),
  submitAnswer: (caseId: string, executionId: string, body: SubmitAnswerRequest) =>
    request<DiagnosticResponse>('POST', `/cases/${caseId}/diagnostics/${executionId}/answers`, body),
  getExecutionStatus: (executionId: string) =>
    request<ExecutionStatusResponse>('GET', `/executions/${executionId}`),
  getArtifact: (executionId: string) =>
    request<ArtifactResponse>('GET', `/executions/${executionId}/artifact`),
}

export type ApiClient = typeof apiClient
