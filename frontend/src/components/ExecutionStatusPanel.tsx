import type { ExecutionStatusResponse } from '../api/types'

export function ExecutionStatusPanel({ status }: { status: ExecutionStatusResponse | null }) {
  if (!status) {
    return (
      <div role="status" aria-busy="true">
        Loading…
      </div>
    )
  }
  return (
    <div role="status">
      <p>
        {status.runner_type} status: <strong>{status.execution_status}</strong>
      </p>
    </div>
  )
}
