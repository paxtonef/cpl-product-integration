import { expect, test } from '@playwright/test'
import { registerAndResolveVehicle, signIn } from './helpers'

// L. Two users (preparation for production, block 3): B never sees A's
// case, by direct URL or in the list; signing out ends access.
test('L. a second user cannot reach the first user\'s case', async ({ page, browser }) => {
  const caseId = await registerAndResolveVehicle(page, { user: 'A' })

  const contextB = await browser.newContext()
  const pageB = await contextB.newPage()
  await pageB.goto(`/cases/${caseId}`)
  await signIn(pageB, 'B')
  await expect(pageB.getByRole('alert')).toHaveText('This item could not be found.')
  await pageB.goto('/')
  await expect(pageB.getByRole('heading', { name: 'Your cases' })).toBeVisible()
  await expect(pageB.getByRole('link', { name: new RegExp(`Case ${caseId.slice(0, 8)}`) })).toHaveCount(0)
  await contextB.close()

  await page.goto('/')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.goto(`/cases/${caseId}`)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})
