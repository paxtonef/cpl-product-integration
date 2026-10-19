import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { apiClient, onUnauthenticated } from '../api/client'

// Every page except /login needs a session: on mount (and so after a
// reload) the CSRF token is recovered from GET /auth/session; any 401
// afterwards (expired or ended session) sends the user back to /login.
export function SessionGate() {
  const [state, setState] = useState<'checking' | 'in' | 'out'>('checking')
  const location = useLocation()

  useEffect(() => {
    let active = true
    apiClient
      .restoreSession()
      .then(() => active && setState('in'))
      .catch(() => active && setState('out'))
    const unsubscribe = onUnauthenticated(() => setState('out'))
    return () => {
      active = false
      unsubscribe()
    }
  }, [])

  if (state === 'checking') {
    return (
      <div role="status" aria-busy="true">
        Checking your session…
      </div>
    )
  }
  if (state === 'out') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}
