import { type Page, expect, test } from '@playwright/test'
import { registerAndResolveVehicle, signIn } from './helpers'

// Q. Clôture PGDR V1, against the assembly with the FAKE sorting transport of the trials
// (E2E_NOTICE_SORTER=faux) and a frontend built WITHOUT the legacy dialogue: the case page links to no
// diagnostic dialogue; no screen of the parcours has a free text field (proposed images, own selection,
// confirmation, restitution, no image recognised, colour); an identity VIR does not establish gives PGDR's
// refusal and, beside it, the safety instructions without notice. Proves the wiring, never a recognition.
const PHOTO = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAGXRFWHRDb21tZW50AEZJQ1RJVkUtUExBVEUtRTJFC2Sn5QAAACBlWElmTU0AKkdQUyA0OC44NU4gRkFVWFZOWlpaMDAwMEUyRTE5LF0GAAAAEUlEQVR4nGPgEpHDihiGlgQA2BMPAcCS07QAAAAASUVORK5CYII=',
  'base64',
)
const FREE_TEXT = 'input[type="text"]:visible, input:not([type]):visible, textarea, [contenteditable]'

async function noFreeText(page: Page) {
  await expect(page.locator(FREE_TEXT)).toHaveCount(0)
}

test('Q1. no dialogue: no legacy link, no free text field on any screen of the parcours', async ({ page }) => {
  if (process.env.E2E_NOTICE_SORTER !== 'faux') throw new Error('E2E_NOTICE_SORTER=faux is not set')
  const caseId = await registerAndResolveVehicle(page, { vin: 'VF3XXXXXXXXXXXXXX', user: 'A' })
  await page.goto(`/cases/${caseId}`)
  await expect(page.getByRole('button', { name: 'Open the manufacturer notice' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Start a diagnostic' })).toHaveCount(0)
  await page.goto(`/cases/${caseId}/diagnostic`)
  await expect(page.locator('textarea')).toHaveCount(0)
  await expect(page.getByText("Tell us what's wrong")).toHaveCount(0)

  await page.goto(`/cases/${caseId}`)
  await page.getByRole('button', { name: 'Open the manufacturer notice' }).click()
  await expect(page).toHaveURL(/\/api\/v1\?p=V1-[0-9a-f]{32}$/)
  await noFreeText(page)
  await page.locator('#vir-continue').click()
  await noFreeText(page)
  await page.locator('#consent-box').check()
  await page.locator('#consent-continue').click()
  await expect(page.locator('#screen-photo')).toBeVisible()
  await page.locator('#photo-input').setInputFiles({ name: 'dash.png', mimeType: 'image/png', buffer: PHOTO })
  await page.locator('#propose-consent').check()
  await page.locator('#photo-propose').click()
  await expect(page.locator('#screen-propositions')).toBeVisible()
  await noFreeText(page)
  await expect(page.locator('#propositions-grid .tile[aria-pressed="true"]')).toHaveCount(0)   // never preselected
  await page.locator('#propositions-grid .tile[data-entry-id="fn_green_lamps"]').click()
  await page.locator('#propositions-continue').click()
  await expect(page.locator('#screen-confirmation')).toBeVisible()
  await noFreeText(page)
  await page.locator('#confirm').click()
  await expect(page.locator('#screen-restitution')).toBeVisible()
  await noFreeText(page)
  await page.locator('#screen-restitution button.return').click()
  await page.locator('#none-match').click()
  await expect(page.locator('#screen-colour')).toBeVisible()
  await noFreeText(page)
  await page.locator('#colour-choices button[data-colour="incertain"]').click()
  await expect(page.locator('#fallback-content')).toHaveAttribute('data-screen', 'red_or_uncertain')
  await noFreeText(page)
})

test('Q2. identity not established: refusal, then the safety instructions without notice', async ({ page }) => {
  await page.goto('/')
  if (await page.getByRole('heading', { name: 'Sign in' }).isVisible()) await signIn(page, 'A')
  await page.goto('/register')
  await page.getByRole('button', { name: 'Register' }).click()
  await page.getByLabel('VIN', { exact: true }).fill('VF1XXXXXXXXXXXXXX')
  await page.getByLabel('Registration country').selectOption('FR')
  await page.getByLabel(/I agree that my VIN or registration number is sent/).check()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('button', { name: 'Continue' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]+/)
  await page.getByRole('button', { name: 'Open the manufacturer notice' }).click()
  await expect(page.getByTestId('notice-refusal').locator('p').first()).toHaveText(
    "L'identité du véhicule n'est pas établie par VIR.",
  )
  await page.getByRole('button', { name: 'Voir les consignes de sécurité' }).click()
  await expect(page).toHaveURL(/\/api\/v1\?p=V1-[0-9a-f]{32}$/)
  await expect(page.locator('#screen-sans-notice')).toBeVisible()
  await expect(page.locator('#sans-notice-message')).toHaveText("L'identité du véhicule n'est pas établie par VIR.")
  await expect(page.locator('#sans-notice-titre')).toHaveText('Aucune notice du constructeur pour ce véhicule')
  await expect(page.locator('.tile')).toHaveCount(0)
  await noFreeText(page)
  await page.getByRole('button', { name: 'Rouge' }).click()
  await expect(page.locator('#sans-notice-screen')).toHaveAttribute('data-screen', 'red_or_uncertain')
  await expect(page.locator('#sans-notice-screen h2')).toHaveText('Arrêtez-vous en sécurité — vérification humaine nécessaire')
})
