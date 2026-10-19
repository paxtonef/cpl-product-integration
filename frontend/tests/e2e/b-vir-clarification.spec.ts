import { expect, test } from '@playwright/test'
import { ensureSignedIn } from './helpers'

// B. VIR clarification path (structuring §21-B): the real AMBIGUOUS-
// triggering fixture (registration_number "AM-BIG-01", confirmed at PI-01's
// own build and reused throughout this project's verification history)
// requires clarification before the journey can proceed.
//
// PI-06-VF-05 repair verification: registerAndResolveVehicle's own final
// assertion (a bare /cases/{id} URL) no longer holds for this fixture --
// the app must now AUTOMATICALLY navigate to /clarification, since the
// real backend's case_status stays IN_PROGRESS for this case and the
// navigation model must derive "clarification needed" from the VIR
// resolution itself, not from case_status alone. This is the actual
// behavior under repair, asserted directly rather than forced via a
// manual page.goto.
test('B. VIR clarification path: automatic routing, then clarify and continue', async ({ page }) => {
  await ensureSignedIn(page)
  await page.goto('/register')
  await page.getByRole('button', { name: 'Register' }).click()
  await expect(page.getByRole('heading', { name: 'Vehicle identity' })).toBeVisible()
  await page.getByLabel("Registration number (if you don't have the VIN)").fill('AM-BIG-01')
  await page.getByLabel('Registration country').selectOption('FR')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('button', { name: 'Continue' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()

  // Automatic navigation to the clarification screen -- no manual goto.
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]+\/clarification$/, { timeout: 15000 })
  await expect(page.getByRole('heading', { name: 'We need a bit more information' })).toBeVisible()
  const caseId = page.url().split('/cases/')[1].split('/clarification')[0]

  // Answer every choice question.
  const selects = page.locator('form[aria-label="Clarification needed"] select')
  const selectCount = await selects.count()
  for (let i = 0; i < selectCount; i++) {
    await selects.nth(i).selectOption({ index: 1 })
  }
  // VIR V1 applies and validates every answer it receives (an arbitrary text
  // as a VIN is refused, VIR-ERR-016): optional free-text questions are left
  // unanswered, as a user without that information would.
  await page.getByRole('button', { name: 'Submit' }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)

  // Same case_id continues -- no fresh vehicle registration was triggered.
  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}`), { timeout: 15000 })

  // The journey should now be able to proceed (possibly requiring another
  // clarification round, or reaching the case hub) -- either is valid per
  // the structuring's own "may need a second round" note. Confirm it is
  // NOT stuck showing the refusal panel (which would indicate the
  // navigation repair regressed journey C).
  await expect(page.getByRole('heading', { name: "We can't proceed with a diagnostic yet" })).not.toBeVisible()
})
