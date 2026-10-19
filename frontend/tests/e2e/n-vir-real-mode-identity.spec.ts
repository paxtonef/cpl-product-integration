import { expect, test } from '@playwright/test'
import { CONSENT_LABEL, ensureSignedIn } from './helpers'

// N. VIR in the product, against VIR in REAL provider mode with its real
// RegCheck and Vincario adapters on FAKE transports
// (tests/vir_real_mode_support.py, fictitious data): run only against that
// assembly (E2E_REAL_MODE_VIN set). It proves the product wiring, never the
// real use of a provider.
function realModeVin(): string {
  const vin = process.env.E2E_REAL_MODE_VIN
  if (!vin) throw new Error('E2E_REAL_MODE_VIN is not set (run against the real-mode assembly)')
  return vin
}

test('N. consent, result with provenance, confirmation, correction, withdrawal, refresh', async ({ page }) => {
  const vin = realModeVin()
  await ensureSignedIn(page, 'A')
  await page.goto('/register')
  await page.getByRole('button', { name: 'Register' }).click()
  await page.getByLabel('VIN', { exact: true }).fill(vin)
  await page.getByLabel('Registration country').selectOption('FR')

  // no lookup without consent
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('alert')).toHaveText(
    'Your consent is needed before your VIN or registration number is looked up.',
  )
  await page.getByLabel(CONSENT_LABEL).check()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('button', { name: 'Continue' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]+$/)

  const details = page.getByRole('region', { name: 'Vehicle identity details' })
  await expect(details).toBeVisible()
  await expect(details.getByRole('note')).toHaveText(
    'These are simulated or test data: they do not come from a confirmed provider lookup.',
  )
  const fields = details.getByRole('table', { name: 'Identified characteristics' })
  await expect(fields.getByRole('row', { name: /^Manufacturer/ })).toContainText('provider-vincario-vin')
  await expect(fields.getByRole('row', { name: /^Model year/ })).toContainText('2019')
  await expect(page.locator('body')).not.toContainText(vin)

  const driven = details.getByRole('group', { name: 'Driven wheels' })
  await driven.getByLabel('Your value for Driven wheels').selectOption('front_wheel_drive')
  await driven.getByRole('button', { name: 'Confirm' }).click()
  await expect(fields.getByRole('row', { name: /^Driven wheels/ })).toContainText('front-wheel drive')
  await expect(fields.getByRole('row', { name: /^Driven wheels/ })).toContainText('user_confirmation')
  await expect(driven).toContainText('Your confirmation: front-wheel drive (applied, not independently verified)')

  await driven.getByLabel('Your value for Driven wheels').selectOption('rear_wheel_drive')
  await driven.getByRole('button', { name: 'Correct' }).click()
  await expect(fields.getByRole('row', { name: /^Driven wheels/ })).toContainText('rear-wheel drive')

  const modelYear = details.getByRole('group', { name: 'Model year' })
  await modelYear.getByLabel('Your value for Model year').fill('2020')
  await modelYear.getByRole('button', { name: 'Confirm' }).click()
  await expect(modelYear).toContainText('Your confirmation: 2020 (kept apart, not applied')
  await expect(fields.getByRole('row', { name: /^Model year/ })).toContainText('Other value: 2020 (driver_confirmation')
  await expect(details.getByRole('region', { name: 'Contradictions' })).toContainText('Model year')

  await driven.getByRole('button', { name: 'Withdraw' }).click()
  await expect(fields.getByRole('row', { name: /^Driven wheels/ })).toHaveCount(0)
  await details.getByRole('button', { name: 'Refresh' }).click()
  await expect(fields.getByRole('row', { name: /^Driven wheels/ })).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText(vin)
})

test('N. a plate shows the providers’ descriptive information apart from the identity', async ({ page }) => {
  const plate = process.env.E2E_REAL_MODE_PLATE
  if (!plate) throw new Error('E2E_REAL_MODE_PLATE is not set (run against the real-mode assembly)')
  await ensureSignedIn(page, 'A')
  await page.goto('/register')
  await page.getByRole('button', { name: 'Register' }).click()
  await page.getByLabel("Registration number (if you don't have the VIN)").fill(plate)
  await page.getByLabel('Registration country').selectOption('FR')
  await page.getByLabel(CONSENT_LABEL).check()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]+$/)
  const details = page.getByRole('region', { name: 'Vehicle identity details' })
  const descriptive = details.getByRole('region', { name: 'Information supplied by the providers' })
  await expect(descriptive).toContainText('Description de version fournie: VERSION-FICTIVE')
  await expect(details.getByRole('table', { name: 'Identified characteristics' })).not.toContainText('VERSION-FICTIVE')
  await expect(details.getByRole('region', { name: 'Unknown' })).toContainText('Model year')
  await expect(page.locator('body')).not.toContainText(plate)
})
