import { expect, test } from '@playwright/test'
import { registerAndResolveVehicle, signIn } from './helpers'

// H. Return to existing Case (structuring §21-H): close the browser
// context entirely, open a new one, navigate directly to /cases/{id}. The
// new context has no session: it is sent to sign in, then back to the case.
test('H. return to existing Case via a genuinely new browser context', async ({ page, browser }) => {
  const caseId = await registerAndResolveVehicle(page)
  await page.close()

  const newContext = await browser.newContext()
  const newPage = await newContext.newPage()
  await newPage.goto(`/cases/${caseId}`)
  await signIn(newPage)
  await expect(newPage).toHaveURL(new RegExp(`/cases/${caseId}$`))

  await expect(newPage.getByRole('heading', { name: 'Vehicle identity resolved' })).toBeVisible()
  await expect(newPage.getByRole('link', { name: 'Start a diagnostic' })).toBeVisible()
  await newContext.close()
})

// The Entry screen lists the user's own cases (it replaced the free
// "return to an existing case" identifier field).
test('H2. Entry screen case list navigates to the case', async ({ page }) => {
  const caseId = await registerAndResolveVehicle(page)
  await page.goto('/')
  await page.getByRole('link', { name: new RegExp(`Case ${caseId.slice(0, 8)}`) }).click()
  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}`))
})
