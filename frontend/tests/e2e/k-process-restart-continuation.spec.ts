import { expect, test } from '@playwright/test'
import { registerAndResolveVehicle, startDiagnostic } from './helpers'

// K. Process-restart continuation (structuring §21-K, added beyond the
// instruction's own 10 mandatory scenarios): the known, honest PGDR
// cross-instance limitation. This test simulates a backend process
// restart by intercepting the answer-submission request with the exact
// real PROCESS_LOCAL_STATE_UNAVAILABLE shape PI-05 itself returns when the
// process-local registry genuinely has no entry for the execution
// (independently confirmed real and reproducible at PI-05's own
// verification) -- a true process-kill-and-restart mid-test is
// impractical to coordinate reliably inside this same test run, so the
// exact documented response shape is used instead, matching this
// project's own established "reproduce the real shape" testing discipline.
test('K. process-restart continuation surfaces the known limitation honestly, never a crash', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)
  await startDiagnostic(page, 'The engine makes a strange noise when accelerating.')
  await expect(page.getByRole('heading', { name: 'One more question' })).toBeVisible()

  await page.route('**/api/cases/*/diagnostics/*/answers', async (route) => {
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({
        error_category: 'PROCESS_LOCAL_STATE_UNAVAILABLE',
        message: 'no process-local PGDR session found for execution ... (known PGDR cross-instance limitation)',
        case_id: caseId,
      }),
    })
  })

  const answer = page.locator('#answer')
  await answer.waitFor({ state: 'attached' })
  await expect(answer).toBeEnabled()
  const tagName = await answer.evaluate((el) => el.tagName.toLowerCase())
  if (tagName === 'select') {
    await answer.selectOption({ index: 1 })
  } else {
    await answer.fill('yes')
  }
  await page.getByRole('button', { name: 'Submit answer' }).click()

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('can no longer accept an answer')
  await expect(alert).not.toContainText('no process-local PGDR session found')
})
