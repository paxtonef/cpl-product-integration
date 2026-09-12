import { expect, test } from '@playwright/test'
import { answerCurrentQuestion, registerAndResolveVehicle, startDiagnostic } from './helpers'

// E. PGDR multiple-question path (structuring §21-E): PGDR's own question
// engine determines the count dynamically (confirmed at PI-03's own build
// to vary by complaint) -- this journey proves the UI genuinely loops an
// unbounded number of times rather than assuming exactly one question.
//
// PI-06-VF-04 repair verification: this is the primary regression test for
// the stale-disabled-form bug. §6 of the repair instruction requires
// proving at least two consecutive BLOCKED/answer cycles AND that the same
// Case and the same PGDR RunnerExecution remain in use throughout (no
// duplicate diagnostic start).
test('E. PGDR multiple-question path: loops through every real question to terminal, same Case/execution throughout', async ({
  page,
  request,
}) => {
  const caseId = await registerAndResolveVehicle(page)
  await startDiagnostic(page, 'The engine makes a strange noise when accelerating.')

  await expect(page.getByRole('heading', { name: 'One more question' })).toBeVisible()

  let questionCount = 0
  for (let i = 0; i < 15; i++) {
    const isResult = await page.getByRole('article', { name: 'Diagnostic result' }).isVisible().catch(() => false)
    if (isResult) break
    // §6/PI-06-VF-04: answerCurrentQuestion itself now waits for the
    // control to be attached and enabled before interacting with it (see
    // helpers.ts) -- the primary regression proof for this bug is that
    // this loop completes at all across multiple real question cycles.
    await answerCurrentQuestion(page)
    questionCount += 1
  }

  await expect(page.getByRole('article', { name: 'Diagnostic result' })).toBeVisible()
  // The real fixture used throughout this project's own backend build
  // (NOISE_COMPLAINT) is confirmed to require more than one question --
  // asserting that explicitly here, not merely tolerating it.
  expect(questionCount).toBeGreaterThan(1)

  // Same Case, same single PGDR RunnerExecution throughout -- no duplicate
  // diagnostic start, confirmed via real history retrieval.
  const historyResponse = await request.get(`/api/cases/${caseId}/history`)
  const history = await historyResponse.json()
  const pgdrExecutions = history.executions.filter((e: { runner_type: string }) => e.runner_type === 'PGDR')
  expect(pgdrExecutions).toHaveLength(1)
  expect(pgdrExecutions[0].execution_status).toBe('COMPLETED')
})
