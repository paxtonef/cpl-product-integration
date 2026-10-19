import { type Page, expect } from '@playwright/test'

export const CONSENT_LABEL =
  'I agree that my VIN or registration number is sent to the vehicle-data providers to identify my vehicle'

// Fictitious accounts created beforehand with the operator command
// (python -m product_integration.auth.cli create-account --password-stdin);
// their logins and passwords are given to the run through the environment.
export function credentials(user: 'A' | 'B' | 'C' = 'A'): { login: string; password: string } {
  const login = process.env[`E2E_LOGIN_${user}`]
  const password = process.env[`E2E_PASSWORD_${user}`]
  if (!login || !password) throw new Error(`E2E_LOGIN_${user} / E2E_PASSWORD_${user} are not set`)
  return { login, password }
}

export async function signIn(page: Page, user: 'A' | 'B' | 'C' = 'A') {
  const { login, password } = credentials(user)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.getByLabel('Login').fill(login)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeHidden()
}

export async function ensureSignedIn(page: Page, user: 'A' | 'B' = 'A') {
  await page.goto('/')
  const signInHeading = page.getByRole('heading', { name: 'Sign in' })
  const home = page.getByRole('heading', { name: 'Vehicle diagnostic' })
  await expect(signInHeading.or(home)).toBeVisible()
  if (await signInHeading.isVisible()) await signIn(page, user)
  await expect(home).toBeVisible()
}

export async function registerAndResolveVehicle(
  page: Page,
  opts: { vin?: string; registrationNumber?: string; user?: 'A' | 'B' | 'C' } = {},
): Promise<string> {
  await ensureSignedIn(page, opts.user ?? 'A')
  await page.goto('/register')
  await page.getByRole('button', { name: 'Register' }).click()
  await expect(page.getByRole('heading', { name: 'Vehicle identity' })).toBeVisible()

  if (opts.registrationNumber) {
    await page.getByLabel("Registration number (if you don't have the VIN)").fill(opts.registrationNumber)
  } else {
    // PI-06-VF-03 repair: exact accessible-name matching. getByLabel('VIN')
    // without `exact` ambiguously matched both this field and "Registration
    // number (if you don't have the VIN)" (the word "VIN" is a substring of
    // that label's own text too) -- confirmed by independent verification.
    // Exact matching is the minimal fix consistent with this file's
    // existing convention of targeting fields by label text throughout.
    await page.getByLabel('VIN', { exact: true }).fill(opts.vin ?? 'VF3XXXXXXXXXXXXXX')
  }
  // VIR V1: the registration country is always the user's explicit choice.
  await page.getByLabel('Registration country').selectOption('FR')
  // A plate or a VIN is looked up only with the user's explicit consent.
  await page.getByLabel(CONSENT_LABEL).check()
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
  // Wait for a genuinely settled #answer control before deciding which
  // kind it is -- a one-shot count() check can observe a transitional DOM
  // state between one question's component unmounting (keyed by
  // question_id, PI-06-VF-04 repair) and the next one mounting, and
  // wrongly commit to the empty branch. waitFor ensures the element is
  // actually attached first.
  const answer = page.locator('#answer')
  await answer.waitFor({ state: 'attached' })
  await expect(answer).toBeEnabled()
  const tagName = await answer.evaluate((el) => el.tagName.toLowerCase())
  if (tagName === 'select') {
    await answer.selectOption({ index: 1 })
  } else {
    await answer.fill('yes')
  }
  await page.getByRole('button', { name: 'Submit answer' }).click()
  // A short settle wait: this app's own state update after a real network
  // round-trip briefly transitions the DOM (old question's component
  // unmounts, the next one mounts, keyed by question_id per the
  // PI-06-VF-04 repair) -- waiting for the *next* heading below already
  // handles this correctly on the next call, but giving the transition a
  // moment here measurably improves reliability against the real backend's
  // own real network latency.
  await page.waitForTimeout(300)
}
