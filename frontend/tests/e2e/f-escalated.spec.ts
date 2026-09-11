import { expect, test } from '@playwright/test'
import { registerAndResolveVehicle, startDiagnostic } from './helpers'

// F. ESCALATED result (structuring §21-F): a complaint matching PGDR's
// actual SafetyEngine rule (confirmed real at PI-03's own build) reaches
// COMPLETED immediately -- never a separate failure status -- and the
// Result screen must show the safety-forward treatment driven by the
// report's own content.
test('F. ESCALATED: reaches terminal immediately, execution status is COMPLETED, safety banner shown', async ({
  page,
  request,
}) => {
  const caseId = await registerAndResolveVehicle(page)
  await startDiagnostic(page, 'There is smoke coming from under the hood and a burning smell.')

  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}/result`))
  await expect(page.getByTestId('safety-banner')).toBeVisible()

  const historyResponse = await request.get(`/api/cases/${caseId}/history`)
  const history = await historyResponse.json()
  const pgdrExecution = history.executions.find((e: { runner_type: string }) => e.runner_type === 'PGDR')
  expect(pgdrExecution.execution_status).toBe('COMPLETED') // never FAILED
})
