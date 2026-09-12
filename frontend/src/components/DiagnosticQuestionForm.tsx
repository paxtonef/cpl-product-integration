import { useState } from 'react'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { DiagnosticQuestionSchema, DiagnosticResponse } from '../api/types'
import { ErrorBanner } from './ErrorBanner'

export function DiagnosticQuestionForm({
  caseId,
  executionId,
  question,
  onAnswered,
}: {
  caseId: string
  executionId: string
  question: DiagnosticQuestionSchema
  onAnswered: (result: DiagnosticResponse) => void
}) {
  const [value, setValue] = useState('')
  const [status, setStatus] = useState<'ready' | 'submitting'>('ready')
  const [error, setError] = useState<ApiError | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    if (!value) {
      setError(new ApiError('VALIDATION', 'Please provide an answer.', 422))
      return
    }
    setStatus('submitting')
    try {
      const result = await apiClient.submitAnswer(caseId, executionId, {
        question_id: question.question_id,
        value,
      })
      // PI-06-VF-04 repair: reset to 'ready' on the success path too --
      // previously only the catch block did this, so a successful
      // submission left the form permanently 'submitting' (and therefore
      // permanently disabled) if this component instance were ever reused
      // for a later question. Combined with the caller now keying this
      // component by question_id (a genuinely fresh mount per question,
      // so this reset is belt-and-suspenders rather than load-bearing on
      // its own), every new question is guaranteed interactable.
      setStatus('ready')
      setValue('')
      onAnswered(result)
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
      setStatus('ready')
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Diagnostic question">
      <h2>One more question</h2>
      {error && <ErrorBanner error={error} />}
      <div>
        <label htmlFor="answer">{question.prompt}</label>
        {question.choices ? (
          <select
            id="answer"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={status === 'submitting'}
          >
            <option value="" disabled>
              Select an answer
            </option>
            {question.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </select>
        ) : (
          <input
            id="answer"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={status === 'submitting'}
          />
        )}
      </div>
      <button type="submit" disabled={status === 'submitting'}>
        {status === 'submitting' ? 'Submitting…' : 'Submit answer'}
      </button>
    </form>
  )
}
