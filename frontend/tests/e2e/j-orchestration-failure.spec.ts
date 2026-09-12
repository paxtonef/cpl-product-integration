import { expect, test } from '@playwright/test'
import { registerAndResolveVehicle } from './helpers'

// J. Orchestration failure (structuring §21-J): a Case-sync failure after a
// valid BLOCKED persist must map to the typed CASE_ORCHESTRATION_FAILURE
// treatment, and the underlying diagnostic must not be reported lost. Same
// interception approach as I, matching the real errors.py response shape
// exactly -- see docs/build/PI_06_FRONTEND_CANDIDATE_EVIDENCE_v0.md for
// the disclosed rationale (reliably reproducing this specific backend
// condition through purely real infrastructure would require coordinating
// fault injection inside the PI-05 process itself mid-test).
test('J. orchestration failure renders the canonical treatment, no raw exception text', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)
  await page.getByRole('link', { name: 'Start a diagnostic' }).click()

  await page.route('**/api/cases/*/diagnostics', async (route) => {
    await route.fulfill({
      status: 502,
      contentType: 'application/json',
      body: JSON.stringify({
        error_category: 'CASE_ORCHESTRATION_FAILURE',
        message: "PGDR outcome 'BLOCKED' was persisted correctly, but Case synchronization failed",
        case_id: caseId,
        execution_id: 'e2e-fake-execution-id',
      }),
    })
  })

  await page.getByLabel("What's happening with your vehicle?").fill('noise')
  await page.getByRole('button', { name: 'Start diagnostic' }).click()

  const alert = page.getByRole('alert')
  await expect(alert).toContainText("catching up your case status")
  await expect(alert).not.toContainText('Case synchronization failed')
})
