import { expect, test } from '@playwright/test'
import { registerAndResolveVehicle } from './helpers'

// H. Return to existing Case (structuring §21-H): close the browser
// context entirely, open a new one, navigate directly to /cases/{id}.
test('H. return to existing Case via a genuinely new browser context', async ({ page, browser }) => {
  const caseId = await registerAndResolveVehicle(page)
  await page.close()

  const newContext = await browser.newContext()
  const newPage = await newContext.newPage()
  await newPage.goto(`/cases/${caseId}`)

  await expect(newPage.getByRole('heading', { name: 'Vehicle identity resolved' })).toBeVisible()
  await expect(newPage.getByRole('link', { name: 'Start a diagnostic' })).toBeVisible()
  await newContext.close()
})

// The Entry screen's own "return to Case" form is also part of this journey.
test('H2. Entry screen return-to-Case form navigates correctly', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)
  await page.goto('/')
  await page.getByLabel('Return to an existing case').fill(caseId)
  await page.getByRole('button', { name: 'Go' }).click()
  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}`))
})
