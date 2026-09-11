import { expect, test } from '@playwright/test'
import { answerCurrentQuestion, registerAndResolveVehicle, startDiagnostic } from './helpers'

// A. Happy path (structuring §21-A): registration -> Case+VIR (resolved) ->
// diagnostic start -> BLOCKED -> answer(s) -> COMPLETED -> result -> history.
test('A. happy path: registration through terminal result and history', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)

  await startDiagnostic(page, 'The engine makes a strange noise when accelerating.')

  // Loop answering questions until the diagnostic reaches a terminal state.
  for (let i = 0; i < 15; i++) {
    if (await page.getByRole('article', { name: 'Diagnostic result' }).isVisible().catch(() => false)) break
    await answerCurrentQuestion(page)
    if (page.url().includes('/result')) break
  }

  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}/result`))
  await expect(page.getByRole('heading', { name: 'Diagnostic result' })).toBeVisible()

  await page.goto(`/cases/${caseId}/history`)
  await expect(page.getByRole('heading', { name: 'Case history' })).toBeVisible()
  await expect(page.getByText('VIR —')).toBeVisible()
  await expect(page.getByText('PGDR —')).toBeVisible()
})
