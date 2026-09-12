import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

export function Entry() {
  const [caseId, setCaseId] = useState('')
  const navigate = useNavigate()

  function handleReturn(event: React.FormEvent) {
    event.preventDefault()
    if (caseId.trim()) {
      navigate(`/cases/${caseId.trim()}`)
    }
  }

  return (
    <main>
      <h1>Vehicle diagnostic</h1>
      <p>
        <Link to="/register">Start a new vehicle registration</Link>
      </p>
      <form onSubmit={handleReturn} aria-label="Return to existing case">
        <label htmlFor="caseId">Return to an existing case</label>
        <input id="caseId" value={caseId} onChange={(event) => setCaseId(event.target.value)} />
        <button type="submit">Go</button>
      </form>
    </main>
  )
}
