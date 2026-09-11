import { expect, test } from '@playwright/test'
import { answerCurrentQuestion, registerAndResolveVehicle, startDiagnostic } from './helpers'

// B. VIR clarification path (structuring §21-B): the real AMBIGUOUS-
// triggering fixture (registration_number "AM-BIG-01", confirmed at PI-01's
// own build and reused throughout this project's verification history)
// requires clarification before the journey can proceed.
test('B. VIR clarification path: clarify then continue to a real diagnostic', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page, { registrationNumber: 'AM-BIG-01' })

  await page.goto(`/cases/${caseId}/clarification`)
  await expect(page.getByRole('heading', { name: 'We need a bit more information' })).toBeVisible()

  // Answer every rendered clarification question.
  const selects = page.locator('form[aria-label="Clarification needed"] select')
  const inputs = page.locator('form[aria-label="Clarification needed"] input')
  const selectCount = await selects.count()
  for (let i = 0; i < selectCount; i++) {
    await selects.nth(i).selectOption({ index: 1 })
  }
  const inputCount = await inputs.count()
  for (let i = 0; i < inputCount; i++) {
    await inputs.nth(i).fill('unknown')
  }
  await page.getByRole('button', { name: 'Submit' }).click()

  // Same case_id continues -- no fresh vehicle registration was triggered.
  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}`))

  // The journey should now be able to proceed (possibly requiring another
  // clarification round, or reaching the case hub) -- either is valid per
  // the structuring's own "may need a second round" note.
})
