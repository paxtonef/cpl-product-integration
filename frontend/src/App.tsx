import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { SessionGate } from './components/SessionGate'
import { AccountPassword } from './routes/AccountPassword'
import { CaseHub } from './routes/CaseHub'
import { Clarification } from './routes/Clarification'
import { Diagnostic } from './routes/Diagnostic'
import { Entry } from './routes/Entry'
import { History } from './routes/History'
import { Login } from './routes/Login'
import { Registration } from './routes/Registration'
import { Result } from './routes/Result'

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<SessionGate />}>
          <Route path="/" element={<Entry />} />
          <Route path="/account/password" element={<AccountPassword />} />
          <Route path="/register" element={<Registration />} />
          <Route path="/cases/:caseId" element={<CaseHub />} />
          <Route path="/cases/:caseId/clarification" element={<Clarification />} />
          <Route path="/cases/:caseId/diagnostic" element={<Diagnostic />} />
          <Route path="/cases/:caseId/result" element={<Result />} />
          <Route path="/cases/:caseId/history" element={<History />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
