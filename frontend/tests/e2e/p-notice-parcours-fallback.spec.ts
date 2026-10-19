import { expect, test } from '@playwright/test'
import { registerAndResolveVehicle } from './helpers'

// P. E: the sorting transport absent (E2E_NOTICE_SORTER=absent) or failing
// (E2E_NOTICE_SORTER=panne, the FAKE transport answering with a failure):
// the complete catalogue in the notice order, with its explanation. Run
// against the assembly configured accordingly. This fallback says nothing
// about the sorting quality.
const EXPLANATION: Record<string, string> = {
  absent: "Aucune image proposée n'est disponible pour ce parcours : toutes les images de la notice sont affichées, dans l'ordre de la notice.",
  panne: 'Les images proposées sont indisponibles pour le moment : toutes les images de la notice sont affichées, dans l\'ordre de la notice.',
}
const ORDER = ['fn_red_fluid', 'fn_amber_sensor', 'fn_green_lamps', 'fn_white_cruise']
const PHOTO = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAGXRFWHRDb21tZW50AEZJQ1RJVkUtUExBVEUtRTJFC2Sn5QAAACBlWElmTU0AKkdQUyA0OC44NU4gRkFVWFZOWlpaMDAwMEUyRTE5LF0GAAAAEUlEQVR4nGPgEpHDihiGlgQA2BMPAcCS07QAAAAASUVORK5CYII=',
  'base64',
)

test('P. sorting absent or failing: the complete catalogue, explained', async ({ page }) => {
  const mode = process.env.E2E_NOTICE_SORTER ?? ''
  if (!(mode in EXPLANATION)) throw new Error('E2E_NOTICE_SORTER must be "absent" or "panne" for this spec')
  const posted: string[] = []
  page.on('request', (r) => { if (r.method() === 'POST') posted.push(r.url()) })
  await registerAndResolveVehicle(page, { vin: 'VF3XXXXXXXXXXXXXX', user: 'A' })
  await page.getByRole('button', { name: 'Open the manufacturer notice' }).click()
  await page.locator('#vir-continue').click()
  await page.locator('#consent-box').check()
  await page.locator('#consent-continue').click()
  await expect(page.locator('#screen-photo')).toBeVisible()
  await page.locator('#photo-input').setInputFiles({ name: 'dash.png', mimeType: 'image/png', buffer: PHOTO })
  if (mode === 'absent') {
    await expect(page.locator('#propose-offer')).toBeHidden()   // the photo stays on the device
    await page.locator('#photo-continue').click()
  } else {
    await page.locator('#propose-consent').check()
    await page.locator('#photo-propose').click()
  }
  await expect(page.locator('#screen-catalogue')).toBeVisible()
  await expect(page.locator('#catalogue-repli .repli-text')).toHaveText(EXPLANATION[mode])
  expect(await page.locator('#catalogue-grid .tile').evaluateAll((ts) => ts.map((t) => (t as HTMLElement).dataset.entryId))).toEqual(ORDER)
  expect(posted.some((u) => u.endsWith('/propositions'))).toBe(mode === 'panne')
})
