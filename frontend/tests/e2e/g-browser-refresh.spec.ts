import { expect, test } from '@playwright/test'
import { answerCurrentQuestion, registerAndResolveVehicle, startDiagnostic } from './helpers'

// G. Browser refresh during journey (structuring §21-G): mid-diagnostic
// (BLOCKED), a hard refresh must correctly re-render from re-fetched state
// (this test runs within the same backend process lifetime, so the
// process-local PGDR registry is still intact -- process RESTART is
// covered separately, K).
test('G. browser refresh mid-diagnostic recovers correctly', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)
  await startDiagnostic(page, 'The engine makes a strange noise when accelerating.')
  await expect(page.getByRole('heading', { name: 'One more question' })).toBeVisible()

  await page.reload()

  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}/diagnostic`))
  // Confirms the case is still genuinely BLOCKED/answerable after refresh --
  // whether via the exact same question form or the disclosed recovery
  // path (structuring §24 item 2), the journey must remain completable.
  await answerCurrentQuestion(page)
})
