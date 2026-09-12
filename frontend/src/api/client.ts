// The one bounded typed API-client boundary for PI-05 (structuring §18).
// Exactly one method per real PI-05 route -- 11 total. Explicitly includes
// createContact/getContact: PI-06-VF-01 found the structuring document's own
// summary list omitted these two, but the authoritative API->UI mapping
// table (structuring §5) always required them; this build accounts for
// them, per the build instruction's own explicit §10 requirement.
import { toApiError } from './errors'
import type {
  ArtifactResponse,
  CaseHistoryResponse,
  CaseStatusResponse,
  CaseVIRResponse,
  ContactResponse,
  CreateContactRequest,
  DiagnosticResponse,
  ExecutionStatusResponse,
  RegisterVehicleRequest,
  RegisterVehicleResponse,
  StartCaseRequest,
  StartDiagnosticRequest,
  SubmitAnswerRequest,
  SubmitClarificationRequest,
} from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as T
}

export const apiClient = {
  createContact: (body: CreateContactRequest) => request<ContactResponse>('POST', '/contacts', body),
  getContact: (contactId: string) => request<ContactResponse>('GET', `/contacts/${contactId}`),
  registerVehicle: (body: RegisterVehicleRequest) =>
    request<RegisterVehicleResponse>('POST', '/vehicles', body),
  startCaseVIR: (body: StartCaseRequest) => request<CaseVIRResponse>('POST', '/cases', body),
  submitClarification: (caseId: string, body: SubmitClarificationRequest) =>
    request<CaseVIRResponse>('POST', `/cases/${caseId}/vir/clarifications`, body),
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
