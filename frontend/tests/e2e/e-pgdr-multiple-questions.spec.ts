import { expect, test } from '@playwright/test'
import { answerCurrentQuestion, registerAndResolveVehicle, startDiagnostic } from './helpers'

// E. PGDR multiple-question path (structuring §21-E): PGDR's own question
// engine determines the count dynamically (confirmed at PI-03's own build
// to vary by complaint) -- this journey proves the UI genuinely loops an
// unbounded number of times rather than assuming exactly one question.
test('E. PGDR multiple-question path: loops through every real question to terminal', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)
  await startDiagnostic(page, 'The engine makes a strange noise when accelerating.')

  let questionCount = 0
  for (let i = 0; i < 15; i++) {
    const isResult = await page.getByRole('article', { name: 'Diagnostic result' }).isVisible().catch(() => false)
    if (isResult) break
    await answerCurrentQuestion(page)
    questionCount += 1
  }

  await expect(page.getByRole('article', { name: 'Diagnostic result' })).toBeVisible()
  // The real fixture used throughout this project's own backend build
  // (NOISE_COMPLAINT) is confirmed to require more than one question --
  // asserting that explicitly here, not merely tolerating it.
  expect(questionCount).toBeGreaterThan(1)
})
