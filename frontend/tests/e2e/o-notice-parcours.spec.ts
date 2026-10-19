import { type Page, type Request, expect, test } from '@playwright/test'
import { registerAndResolveVehicle, signIn } from './helpers'

// O. PGDR's V1 notice parcours in the product, against the assembly whose PGDR
// has a FICTIVE notice for VIR's simulated Peugeot 3008 II and the FAKE
// sorting transport (E2E_NOTICE_SORTER=faux): C photo -> proposed images ->
// selection -> notice and Premier Constat, D proposals not recognised ->
// complete catalogue, F no image recognised -> red screen, G identity not
// established -> refusal, and the parcours of one user refused to another.
// Proves the wiring and the rights, never any recognition quality.
function requireFakeSorter() {
  if (process.env.E2E_NOTICE_SORTER !== 'faux') {
    throw new Error('E2E_NOTICE_SORTER=faux is not set (run against the assembly with the fake sorting transport)')
  }
}

const RECIPIENT = "Composant de tri d'essai (faux transport)"
const ORDER = ['fn_red_fluid', 'fn_amber_sensor', 'fn_green_lamps', 'fn_white_cruise']
const PLATE = 'FICTIVE-PLATE-E2E'
const VIN = 'FAUXVNZZZ0000E2E1'
// A fictive dashboard photo (PNG) whose metadata names the plate, the VIN and a position.
const PHOTO = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAGXRFWHRDb21tZW50AEZJQ1RJVkUtUExBVEUtRTJFC2Sn5QAAACBlWElmTU0AKkdQUyA0OC44NU4gRkFVWFZOWlpaMDAwMEUyRTE5LF0GAAAAEUlEQVR4nGPgEpHDihiGlgQA2BMPAcCS07QAAAAASUVORK5CYII=',
  'base64',
)

async function openNotice(page: Page): Promise<string> {
  await page.getByRole('button', { name: 'Open the manufacturer notice' }).click()
  await expect(page).toHaveURL(/\/api\/v1\?p=V1-[0-9a-f]{32}$/)
  await page.locator('#vir-continue').click()
  await page.locator('#consent-box').check()
  await page.locator('#consent-continue').click()
  await expect(page.locator('#screen-photo')).toBeVisible()
  return new URL(page.url()).searchParams.get('p') as string
}

async function propose(page: Page) {
  await expect(page.locator('#propose-offer')).toBeVisible()
  await expect(page.locator('#propose-consent-text')).toContainText(`« ${RECIPIENT} »`)
  await expect(page.locator('#photo-propose')).toBeDisabled()
  await page.locator('#photo-input').setInputFiles({ name: 'dash.png', mimeType: 'image/png', buffer: PHOTO })
  await expect(page.locator('#photo-propose')).toBeDisabled()
  await page.locator('#propose-consent').check()
  await page.locator('#photo-propose').click()
}

const ids = (page: Page, sel: string) => page.locator(sel).evaluateAll((ts) => ts.map((t) => (t as HTMLElement).dataset.entryId))

test('O1. photo, proposed images, own selection, notice and Premier Constat; refused to another user', async ({ page, browser }) => {
  requireFakeSorter()
  const requests: Request[] = []
  const blocked: string[] = []
  page.on('request', (r) => requests.push(r))
  page.on('console', (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) blocked.push(m.text()) })
  await registerAndResolveVehicle(page, { vin: 'VF3XXXXXXXXXXXXXX', user: 'A' })
  const pid = await openNotice(page)
  await propose(page)

  await expect(page.locator('#screen-propositions')).toBeVisible()
  expect(await ids(page, '#propositions-grid .tile')).toEqual(['fn_red_fluid', 'fn_green_lamps']) // notice order
  expect(await ids(page, '#propositions-grid .tile[aria-pressed="true"]')).toEqual([])          // nothing chosen
  await expect(page.locator('#propositions-fake')).toBeVisible()
  await expect(page.locator('#propositions-catalogue')).toBeVisible()
  await expect(page.locator('#propositions-continue')).toBeDisabled()
  for (const img of await page.locator('#propositions-grid img').all()) {
    expect(await img.evaluate((i) => (i as HTMLImageElement).complete && (i as HTMLImageElement).naturalWidth > 0)).toBe(true)
  }
  await page.locator('#propositions-grid .tile[data-entry-id="fn_green_lamps"]').click()
  await page.locator('#propositions-continue').click()
  await expect(page.locator('#screen-confirmation')).toBeVisible()
  await page.locator('#confirm').click()
  await expect(page.locator('#screen-restitution')).toBeVisible()
  await expect(page.locator('#premier-constat')).not.toBeEmpty()
  await expect(page.locator('article.restitution[data-entry-id="fn_green_lamps"] .meaning')).toHaveText(
    'The fictive green light shows that the fictive lamps are on.',
  )
  expect(blocked).toEqual([]) // PGDR's page runs under PI's script-hash CSP

  // Only the product origin was contacted; the photo left re-encoded (JPEG pixels), without its metadata.
  const origin = new URL(page.url()).origin
  for (const r of requests) expect(r.url().startsWith(origin) || r.url().startsWith('blob:') || r.url().startsWith('data:')).toBe(true)
  const posted = requests.filter((r) => r.method() === 'POST' && r.url().endsWith('/propositions'))
  expect(posted).toHaveLength(1)
  const sent = Buffer.from(JSON.parse(posted[0].postData() as string).photo_base64, 'base64')
  expect(sent.subarray(0, 3)).toEqual(Buffer.from([0xff, 0xd8, 0xff]))
  for (const marker of [PLATE, VIN, 'GPS', 'tEXt', 'Exif']) expect(sent.includes(Buffer.from(marker))).toBe(false)

  // Another signed-in user: the same page link shows nothing of A's parcours.
  const other = await browser.newContext()
  const pageB = await other.newPage()
  await pageB.goto('/login')
  await signIn(pageB, 'B')
  await pageB.goto(`/api/v1?p=${pid}`)
  await expect(pageB.locator('#screen-error')).toBeVisible()
  await expect(pageB.locator('#error-text')).toHaveText('Parcours inconnu ou expiré.')
  const assetUrl = await page.locator('article.restitution img').first().getAttribute('src')
  expect((await pageB.request.get(assetUrl as string)).status()).toBe(404)
  expect((await pageB.request.get(`/api/v1/parcours/${pid}/catalogue`)).status()).toBe(404)
  await other.close()
})

test('O2. proposals not recognised, complete catalogue, no image recognised, red screen', async ({ page }) => {
  requireFakeSorter()
  await registerAndResolveVehicle(page, { vin: 'VF3XXXXXXXXXXXXXX', user: 'A' })
  await openNotice(page)
  await propose(page)
  await expect(page.locator('#screen-propositions')).toBeVisible()
  await page.locator('#propositions-catalogue').click()
  await expect(page.locator('#screen-catalogue')).toBeVisible()
  expect(await ids(page, '#catalogue-grid .tile')).toEqual(ORDER)
  expect(await ids(page, '#catalogue-grid .tile[aria-pressed="true"]')).toEqual([])
  await page.locator('#none-match').click()
  await expect(page.locator('#screen-colour')).toBeVisible()
  await page.locator('#colour-choices button[data-colour="rouge"]').click()
  await expect(page.locator('#screen-fallback')).toBeVisible()
  await expect(page.locator('#fallback-content')).toHaveAttribute('data-screen', 'red_or_uncertain')
})

test('O3. complete catalogue reached from the proposals, own selection confirmed', async ({ page }) => {
  requireFakeSorter()
  await registerAndResolveVehicle(page, { vin: 'VF3XXXXXXXXXXXXXX', user: 'A' })
  await openNotice(page)
  await propose(page)
  await page.locator('#propositions-catalogue').click()
  await page.locator('#catalogue-grid .tile[data-entry-id="fn_amber_sensor"]').click()
  await page.locator('#selection-continue').click()
  await page.locator('#confirm').click()
  await expect(page.locator('#screen-restitution')).toBeVisible()
  await expect(page.locator('article.restitution[data-entry-id="fn_amber_sensor"]')).toBeVisible()
})

test('O4. identity not established by VIR: PGDR opens nothing and says why', async ({ page }) => {
  requireFakeSorter()
  await page.goto('/')
  const signInHeading = page.getByRole('heading', { name: 'Sign in' })
  if (await signInHeading.isVisible()) await signIn(page, 'A')
  await page.goto('/register')
  await page.getByRole('button', { name: 'Register' }).click()
  await page.getByLabel('VIN', { exact: true }).fill('VF1XXXXXXXXXXXXXX')
  await page.getByLabel('Registration country').selectOption('FR')
  await page.getByLabel(/I agree that my VIN or registration number is sent/).check()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('button', { name: 'Continue' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]+/)
  const caseId = new URL(page.url()).pathname.split('/')[2]
  await page.goto(`/cases/${caseId}`)
  await page.getByRole('button', { name: 'Open the manufacturer notice' }).click()
  await expect(page.getByTestId('notice-refusal')).toHaveText("L'identité du véhicule n'est pas établie par VIR.")
  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}$`))
})
