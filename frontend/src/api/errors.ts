// Normalizes PI-05's real ProductAPIError body shape ({error_category, message, ...extra})
// into one typed ApiError. Mirrors src/product_integration/api/errors.py's
// ProductAPIErrorCategory exactly — no category invented here.

export const ApiErrorCategory = {
  NOT_FOUND: 'NOT_FOUND',
  CROSS_RESOURCE_MISMATCH: 'CROSS_RESOURCE_MISMATCH',
  AUTHORITY_REJECTION: 'AUTHORITY_REJECTION',
  CONFLICT: 'CONFLICT',
  VIR_TECHNICAL_FAILURE: 'VIR_TECHNICAL_FAILURE',
  VIR_NON_RESOLUTION: 'VIR_NON_RESOLUTION',
  PGDR_TECHNICAL_FAILURE: 'PGDR_TECHNICAL_FAILURE',
  CPL_PERSISTENCE_FAILURE: 'CPL_PERSISTENCE_FAILURE',
  CASE_ORCHESTRATION_FAILURE: 'CASE_ORCHESTRATION_FAILURE',
  PROCESS_LOCAL_STATE_UNAVAILABLE: 'PROCESS_LOCAL_STATE_UNAVAILABLE',
  UNEXPECTED: 'UNEXPECTED',
} as const

export type ApiErrorCategoryValue = (typeof ApiErrorCategory)[keyof typeof ApiErrorCategory]

export class ApiError extends Error {
  readonly category: string
  readonly status: number
  readonly extra: Record<string, unknown>

  constructor(category: string, message: string, status: number, extra: Record<string, unknown> = {}) {
    super(message)
    this.category = category
    this.status = status
    this.extra = extra
  }
}

export async function toApiError(response: Response): Promise<ApiError> {
  let body: Record<string, unknown> = {}
  try {
    body = await response.json()
  } catch {
    // response had no JSON body at all — genuinely unexpected, never invent backend detail
  }
  const category = typeof body.error_category === 'string' ? body.error_category : ApiErrorCategory.UNEXPECTED
  const message = typeof body.message === 'string' ? body.message : 'Something went wrong.'
  const { error_category: _c, message: _m, ...extra } = body
  return new ApiError(category, message, response.status, extra)
}
