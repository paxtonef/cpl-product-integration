import { expect, test } from '@playwright/test'
import { credentials, registerAndResolveVehicle, signIn } from './helpers'

// M. Password change by the signed-in user (account C, used by this spec
// only): the current password is required, every session ends on success,
// the old password no longer works, the new one does, and the user's cases
// are still there.
test('M. a user changes their password and keeps their account', async ({ page, browser }) => {
  const { login, password } = credentials('C')
  const newPassword = process.env.E2E_NEW_PASSWORD_C
  if (!newPassword) throw new Error('E2E_NEW_PASSWORD_C is not set')

  const caseId = await registerAndResolveVehicle(page, { user: 'C' })
  await page.goto('/')
  const caseLink = page.getByRole('link', { name: new RegExp(`Case ${caseId.slice(0, 8)}`) })
  await expect(caseLink).toBeVisible()

  const other = await browser.newContext()
  const otherPage = await other.newPage()
  await otherPage.goto('/')
  await signIn(otherPage, 'C')

  await page.getByRole('link', { name: 'Change password' }).click()
  await expect(page.getByRole('heading', { name: 'Change password' })).toBeVisible()
  await page.getByLabel('Current password').fill('not-the-current-password')
  await page.getByLabel('New password', { exact: true }).fill(newPassword)
  await page.getByLabel('New password (again)').fill(newPassword)
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(page.getByRole('alert')).toHaveText(
    'The current password is incorrect, or there were too many attempts. Please try again later.',
  )

  await page.getByLabel('Current password').fill(password)
  await page.getByLabel('New password', { exact: true }).fill(newPassword)
  await page.getByLabel('New password (again)').fill(newPassword)
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('status')).toHaveText(
    'Your password has been changed. Please sign in with your new password.',
  )

  // the other session ended too
  await otherPage.reload()
  await expect(otherPage.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await other.close()

  // old password refused, new password accepted, same cases
  await page.getByLabel('Login').fill(login)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toHaveText('Invalid login or password.')
  await page.getByLabel('Password').fill(newPassword)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Vehicle diagnostic' })).toBeVisible()
  await expect(caseLink).toBeVisible()
  await caseLink.click()
  await expect(page.getByRole('heading', { name: 'Vehicle identity resolved' })).toBeVisible()
})
