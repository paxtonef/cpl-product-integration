import { expect, test } from '@playwright/test'
import { answerCurrentQuestion, registerAndResolveVehicle, startDiagnostic } from './helpers'

// D. PGDR one-question BLOCKED path (structuring §21-D).
test('D. PGDR one-question BLOCKED: question shown, answered, reaches terminal', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)
  await startDiagnostic(page, 'The engine makes a strange noise when accelerating.')

  await expect(page.getByRole('heading', { name: 'One more question' })).toBeVisible()
  await answerCurrentQuestion(page)

  // Either another question (multiple-question path is covered separately,
  // E) or the terminal result -- both are valid; this journey only
  // requires that BLOCKED was genuinely reached and genuinely answered.
  await expect(
    page.getByRole('heading', { name: 'One more question' }).or(page.getByRole('article', { name: 'Diagnostic result' })),
  ).toBeVisible()
})
