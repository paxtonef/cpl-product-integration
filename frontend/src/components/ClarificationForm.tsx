import { useState } from 'react'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { ClarificationQuestionPayload } from '../api/types'
import { ErrorBanner } from './ErrorBanner'

export function ClarificationForm({
  caseId,
  questions,
  onSubmitted,
}: {
  caseId: string
  questions: ClarificationQuestionPayload[]
  onSubmitted: () => void
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [status, setStatus] = useState<'ready' | 'submitting'>('ready')
  const [error, setError] = useState<ApiError | null>(null)

  const requiredUnanswered = questions.filter((q) => q.required !== false && !answers[q.question_id])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    if (requiredUnanswered.length > 0) {
      setError(new ApiError('VALIDATION', 'Please answer all required questions.', 422))
      return
    }
    setStatus('submitting')
    try {
      await apiClient.submitClarification(caseId, {
        answers: Object.entries(answers).map(([question_id, value]) => ({ question_id, value })),
      })
      onSubmitted()
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
      setStatus('ready')
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Clarification needed">
      <h2>We need a bit more information</h2>
      {error && <ErrorBanner error={error} />}
      {questions.map((question) => (
        <div key={question.question_id}>
          <label htmlFor={question.question_id}>{question.prompt}</label>
          {question.choices ? (
            <select
              id={question.question_id}
              value={answers[question.question_id] ?? ''}
              onChange={(event) =>
                setAnswers((prev) => ({ ...prev, [question.question_id]: event.target.value }))
              }
              disabled={status === 'submitting'}
            >
              <option value="" disabled>
                Select an answer
              </option>
              {question.choices.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label ?? choice.value}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={question.question_id}
              value={answers[question.question_id] ?? ''}
              onChange={(event) =>
                setAnswers((prev) => ({ ...prev, [question.question_id]: event.target.value }))
              }
              disabled={status === 'submitting'}
            />
          )}
        </div>
      ))}
      <button type="submit" disabled={status === 'submitting'}>
        {status === 'submitting' ? 'Submitting…' : 'Submit'}
      </button>
    </form>
  )
}
