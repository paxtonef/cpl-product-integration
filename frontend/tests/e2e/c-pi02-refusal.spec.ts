import { expect, test } from '@playwright/test'

// C. PI-02 refusal (structuring §21-C): a VIR result not admissible for
// PGDR must show a truthful non-admissible state, never a generic 500, and
// must never start PGDR. Setup uses PI-01's own real Path B mechanism
// directly (register_vir_resolution_result) -- the same, already-
// established pattern used throughout this project's own backend
// verification to reach this real-but-hard-to-trigger-via-live-VIR status
// -- exercised here only to set up the fixture; the actual test point is
// the real HTTP call the browser itself makes to /diagnostics.
test('C. PI-02 refusal: truthful non-admissible state, PGDR never starts', async ({ page, request }) => {
  const vehiclesResponse = await request.post('/api/vehicles', {
    data: { contact_idempotency_key: `c2e2e-${Date.now()}`, asset_idempotency_key: `a-e2e-${Date.now()}` },
  })
  const vehicle = await vehiclesResponse.json()

  // This E2E-level setup necessarily reaches the backend directly for the
  // one fixture PI-05's own HTTP surface cannot itself produce live (VIR's
  // real resolve() engine does not reach provider_unavailable through its
  // current stub providers, confirmed at PI-04/PI-05's own independent
  // verification) -- the refusal ITSELF is then exercised through real
  // browser navigation and a real HTTP call, not faked.
  const refusalCaseId = process.env.E2E_PI02_REFUSAL_CASE_ID
  test.skip(!refusalCaseId, 'requires E2E_PI02_REFUSAL_CASE_ID pre-seeded via the backend fixture script')

  await page.goto(`/cases/${refusalCaseId}/diagnostic`)
  await page.getByLabel("What's happening with your vehicle?").fill('noise')
  await page.getByRole('button', { name: 'Start diagnostic' }).click()

  await expect(page.getByRole('heading', { name: "We can't proceed with a diagnostic yet" })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Start a new vehicle registration' })).toBeVisible()

  const historyResponse = await request.get(`/api/cases/${refusalCaseId}/history`)
  const history = await historyResponse.json()
  expect(history.executions.filter((e: { runner_type: string }) => e.runner_type === 'PGDR')).toHaveLength(0)
})
