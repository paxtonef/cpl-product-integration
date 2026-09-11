import { Link } from 'react-router-dom'

export function RefusalPanel({ detail }: { detail?: string | null }) {
  return (
    <div role="status">
      <h2>We can't proceed with a diagnostic yet</h2>
      <p>
        Identity resolution did not produce a result our diagnostic service can use.{' '}
        {detail && <span>{detail}</span>}
      </p>
      <p>
        <Link to="/register">Start a new vehicle registration</Link>
      </p>
    </div>
  )
}
