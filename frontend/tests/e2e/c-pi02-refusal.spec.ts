import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// C. PI-02 refusal (structuring §21-C): a VIR result not admissible for
// PGDR must show a truthful non-admissible state, never a generic 500, and
// must never start PGDR. Setup uses PI-01's own real Path B mechanism
// directly (register_vir_resolution_result, via fixtures/
// setup_pi02_refusal_case.py) -- the same, already-established pattern
// used throughout this project's own backend verification to reach this
// real-but-hard-to-trigger-via-live-VIR status -- exercised here only to
// set up the fixture and trigger the one real PI-02 refusal call. The
// actual test point is real browser navigation to the already-refused
// Case, exercising the PI-06-VF-05 navigation repair directly.
function setupRefusalCase(): string {
  const pythonBin = process.env.E2E_BACKEND_PYTHON ?? 'python3'
  const apiBaseUrl = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'
  const output = execFileSync(
    pythonBin,
    [path.join(__dirname, 'fixtures', 'setup_pi02_refusal_case.py'), apiBaseUrl],
    { encoding: 'utf-8' },
  )
  return output.trim()
}

test('C. PI-02 refusal: truthful non-admissible state, PGDR never starts', async ({ page, request }) => {
  const refusalCaseId = setupRefusalCase()

  // The real user path: they already tried (or the fixture already
  // triggered) diagnostics start once, got refused, and are now viewing
  // (or returning to) this Case -- confirms the PI-06-VF-05 navigation
  // repair routes WAITING_FOR_EXTERNAL_INFORMATION straight to the
  // truthful refusal state without re-showing a complaint form.
  await page.goto(`/cases/${refusalCaseId}/diagnostic`)

  await expect(page.getByRole('heading', { name: "We can't proceed with a diagnostic yet" })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Start a new vehicle registration' })).toBeVisible()
  // Never the clarification fallback message.
  await expect(page.getByText(/no further clarification is/i)).not.toBeVisible()

  const historyResponse = await request.get(`/api/cases/${refusalCaseId}/history`)
  const history = await historyResponse.json()
  expect(history.executions.filter((e: { runner_type: string }) => e.runner_type === 'PGDR')).toHaveLength(0)
})
