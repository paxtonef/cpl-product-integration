import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiClient } from '../api/client'
import type { CaseListEntry } from '../api/types'

export function Entry() {
  const [cases, setCases] = useState<CaseListEntry[] | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    apiClient
      .listCases()
      .then((response) => setCases(response.cases))
      .catch(() => setCases([]))
  }, [])

  async function handleLogout() {
    try {
      await apiClient.logout()
    } finally {
      navigate('/login', { replace: true })
    }
  }

  return (
    <main>
      <h1>Vehicle diagnostic</h1>
      <p>
        <Link to="/register">Start a new vehicle registration</Link>
      </p>
      <section aria-label="Your cases">
        <h2>Your cases</h2>
        {cases === null ? (
          <p role="status">Loading…</p>
        ) : cases.length === 0 ? (
          <p>No case yet.</p>
        ) : (
          <ul>
            {cases.map((c) => (
              <li key={c.case_id}>
                <Link to={`/cases/${c.case_id}`}>
                  Case {c.case_id.slice(0, 8)} — {c.case_status}
                  {c.created_at ? ` — ${new Date(c.created_at).toLocaleString()}` : ''}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      <button type="button" onClick={handleLogout}>
        Sign out
      </button>
    </main>
  )
}
