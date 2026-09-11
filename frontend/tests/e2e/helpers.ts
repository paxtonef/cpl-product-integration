import { type Page, expect } from '@playwright/test'

export async function registerAndResolveVehicle(
  page: Page,
  opts: { vin?: string; registrationNumber?: string } = {},
): Promise<string> {
  await page.goto('/register')
  await page.getByLabel('Your name').fill('E2E Test User')
  await page.getByRole('button', { name: 'Register' }).click()
  await expect(page.getByRole('heading', { name: 'Vehicle identity' })).toBeVisible()

  if (opts.registrationNumber) {
    await page.getByLabel("Registration number (if you don't have the VIN)").fill(opts.registrationNumber)
  } else {
    await page.getByLabel('VIN').fill(opts.vin ?? 'VF3XXXXXXXXXXXXXX')
  }
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('button', { name: 'Continue' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]+$/)
  const url = page.url()
  const caseId = url.split('/cases/')[1]
  return caseId
}

export async function startDiagnostic(page: Page, complaint: string) {
  await page.getByRole('link', { name: 'Start a diagnostic' }).click()
  await expect(page.getByLabel("What's happening with your vehicle?")).toBeVisible()
  await page.getByLabel("What's happening with your vehicle?").fill(complaint)
  await page.getByRole('button', { name: 'Start diagnostic' }).click()
}

export async function answerCurrentQuestion(page: Page) {
  await expect(page.getByRole('heading', { name: 'One more question' })).toBeVisible()
  const select = page.locator('select#answer')
  const input = page.locator('input#answer')
  if (await select.count()) {
    await select.selectOption({ index: 1 })
  } else {
    await input.fill('yes')
  }
  await page.getByRole('button', { name: 'Submit answer' }).click()
}
