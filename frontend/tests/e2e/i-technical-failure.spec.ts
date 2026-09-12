import { expect, test } from '@playwright/test'
import { registerAndResolveVehicle } from './helpers'

// I. Technical failure (structuring §21-I): a genuine PGDR/VIR technical
// failure must render the canonical error treatment (never raw exception
// text), and retry must succeed once the fault clears. This test drives
// the failure by intercepting the frontend's own outgoing request and
// injecting a real 502 PGDR_TECHNICAL_FAILURE-shaped response once, then
// letting the real request through on retry -- this exercises the actual
// frontend error-handling code path against a realistic backend error
// shape, without needing to coordinate fault injection inside the real
// PI-05 process itself for this particular browser-level assertion.
test('I. technical failure renders the canonical error treatment and clears on retry', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)
  await page.getByRole('link', { name: 'Start a diagnostic' }).click()

  let failed = false
  await page.route('**/api/cases/*/diagnostics', async (route) => {
    if (!failed) {
      failed = true
      await route.fulfill({
        status: 502,
        contentType: 'application/json',
        body: JSON.stringify({ error_category: 'PGDR_TECHNICAL_FAILURE', message: 'raw internal backend detail' }),
      })
      return
    }
    await route.continue()
  })

  await page.getByLabel("What's happening with your vehicle?").fill('noise')
  await page.getByRole('button', { name: 'Start diagnostic' }).click()

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('temporarily unavailable')
  await expect(alert).not.toContainText('raw internal backend detail')

  // Retry: the second attempt goes through to the real backend.
  await page.getByRole('button', { name: 'Start diagnostic' }).click()
  await expect(page.getByRole('heading', { name: 'One more question' })).toBeVisible({ timeout: 15000 })
})
