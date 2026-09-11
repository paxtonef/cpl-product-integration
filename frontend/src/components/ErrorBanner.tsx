import { ApiError, ApiErrorCategory } from '../api/errors'

const CATEGORY_MESSAGE: Record<string, string> = {
  [ApiErrorCategory.NOT_FOUND]: 'This item could not be found.',
  [ApiErrorCategory.CROSS_RESOURCE_MISMATCH]: 'This item could not be found.',
  [ApiErrorCategory.AUTHORITY_REJECTION]: "This action isn't permitted.",
  [ApiErrorCategory.CONFLICT]: "This can't be completed in the current state. Try refreshing.",
  [ApiErrorCategory.VIR_TECHNICAL_FAILURE]: 'Vehicle identity lookup is temporarily unavailable. Please try again.',
  [ApiErrorCategory.VIR_NON_RESOLUTION]: 'Vehicle identity lookup is temporarily unavailable. Please try again.',
  [ApiErrorCategory.PGDR_TECHNICAL_FAILURE]: 'The diagnostic service is temporarily unavailable. Please try again.',
  [ApiErrorCategory.CPL_PERSISTENCE_FAILURE]: "We couldn't save your progress. Please try again.",
  [ApiErrorCategory.CASE_ORCHESTRATION_FAILURE]:
    "Your last action was recorded, but we're still catching up your case status. Please refresh in a moment.",
  [ApiErrorCategory.PROCESS_LOCAL_STATE_UNAVAILABLE]:
    "This diagnostic session can no longer accept an answer here. Please contact support to continue this case.",
  [ApiErrorCategory.UNEXPECTED]: 'Something went wrong. Please try again.',
}

// Client-side-only category for form validation errors constructed by this
// frontend itself (never returned by PI-05) -- its own `.message` is
// already a real, user-facing string written by the component that raised
// it, so it is rendered directly rather than mapped to a canned string.
const CLIENT_VALIDATION_CATEGORY = 'VALIDATION'

export function ErrorBanner({ error }: { error: ApiError }) {
  const message =
    error.category === CLIENT_VALIDATION_CATEGORY
      ? error.message
      : (CATEGORY_MESSAGE[error.category] ?? CATEGORY_MESSAGE[ApiErrorCategory.UNEXPECTED])
  return (
    <div role="alert" className="error-banner" data-category={error.category}>
      <p>{message}</p>
    </div>
  )
}
