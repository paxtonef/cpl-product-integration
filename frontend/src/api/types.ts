// PI-05 request/response types — mirror src/product_integration/api/schemas.py
// field-for-field. Do not add fields not present in the real backend schemas.

export interface ContactResponse {
  contact_id: string
  contact_type?: string | null
  display_name?: string | null
}

export interface CreateContactRequest {
  contact_type?: string
  display_name?: string | null
  idempotency_key: string
}

export interface RegisterVehicleRequest {
  existing_contact_id?: string | null
  contact_type?: string
  display_name?: string | null
  asset_domain?: string
  asset_type?: string
  contact_idempotency_key: string
  asset_idempotency_key: string
}

export interface RegisterVehicleResponse {
  outcome: string
  contact_id?: string | null
  asset_id?: string | null
  detail?: string | null
}

export interface ConsentInputSchema {
  external_lookup_allowed: boolean
}

export interface StartCaseRequest {
  contact_id: string
  asset_id: string
  request_id: string
  vin?: string | null
  registration_number?: string | null
  registration_country_code?: string | null
  manufacturer?: string | null
  model?: string | null
  consent: ConsentInputSchema
  case_idempotency_key: string
}

export interface CaseVIRResponse {
  outcome: string
  contact_id?: string | null
  asset_id?: string | null
  case_id?: string | null
  vir_execution_id?: string | null
  vir_artifact_id?: string | null
  vir_resolution_status?: string | null
  detail?: string | null
}

export interface ClarificationAnswerSchema {
  question_id: string
  value: unknown
}

export interface SubmitClarificationRequest {
  answers: ClarificationAnswerSchema[]
}

export interface StartDiagnosticRequest {
  complaint_text: string
  consent_media_analysis_allowed?: boolean
  consent_report_storage_allowed?: boolean
}

export interface SubmitAnswerRequest {
  question_id: string
  value: unknown
}

export interface DiagnosticQuestionSchema {
  question_id: string
  prompt: string
  choices?: string[] | null
}

export interface DiagnosticResponse {
  outcome: string
  case_id?: string | null
  execution_id?: string | null
  blocked: boolean
  terminal: boolean
  pending_questions: DiagnosticQuestionSchema[]
  artifact_id?: string | null
  detail?: string | null
}

export interface ExecutionStatusResponse {
  execution_id: string
  runner_type: string
  execution_status: string
  blocked: boolean
  terminal: boolean
  updated_at?: string | null
  artifact_id?: string | null
}

export interface CaseStatusResponse {
  case_id: string
  case_status: string
  current_execution_id?: string | null
  contact_id?: string | null
  asset_id?: string | null
}

// GaragePreparationReport's real field set — mirror pgdr.models.GaragePreparationReport exactly.
export interface GaragePreparationReport {
  report_id: string
  vehicle: Record<string, unknown>
  customer_reported_problem: string
  symptom_summary: Record<string, unknown>[]
  onset_and_evolution: Record<string, unknown>
  reproduction_conditions?: Record<string, unknown> | null
  warning_indicators: Record<string, unknown>[]
  safety_information: Record<string, unknown>
  recent_vehicle_events: Record<string, unknown>[]
  evidence_index: Record<string, unknown>[]
  systems_to_examine: Record<string, unknown>[]
  suggested_professional_checks: string[]
  unresolved_questions: string[]
  contradictions: Record<string, unknown>[]
  limitations: string[]
  generated_at: string
}

export interface ArtifactResponse {
  artifact_id: string
  execution_id: string
  artifact_type: string
  artifact_status: string
  payload: Record<string, unknown>
}

export interface HistoryExecutionEntry {
  execution_id: string
  runner_type: string
  execution_status: string
  artifact_id?: string | null
}

export interface CaseHistoryResponse {
  case_id: string
  case_status: string
  current_execution_id?: string | null
  contact_id?: string | null
  asset_id?: string | null
  executions: HistoryExecutionEntry[]
}

// vir.domain.models.ClarificationQuestion's real field set (subset actually
// needed for rendering — question_id/prompt/choices — the full model also
// carries target_field/reason/question_type/required, which this frontend
// does not need to render a working clarification form).
export interface ClarificationChoice {
  value: string
  label?: string
}

export interface ClarificationQuestionPayload {
  question_id: string
  prompt: string
  choices?: ClarificationChoice[] | null
  required?: boolean
}
