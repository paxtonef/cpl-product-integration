import { defineConfig, devices } from '@playwright/test'

// Definitive acceptance: real PI-05, real PostgreSQL, real VIR, real PGDR --
// this config assumes those are already running (see docs/build/
// PI_06_FRONTEND_CANDIDATE_EVIDENCE_v0.md for the exact process/setup used
// during this build) and only starts the frontend dev server itself.
// E2E_BASE_URL set: the run targets an already-running production entry
// point (built frontend + /api, HTTPS, possibly a self-signed test
// certificate) and starts no Vite server.
const externalBaseUrl = process.env.E2E_BASE_URL

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: externalBaseUrl ?? 'http://127.0.0.1:5173',
    ignoreHTTPSErrors: Boolean(process.env.E2E_IGNORE_HTTPS_ERRORS),
    trace: 'retain-on-failure',
  },
  webServer: externalBaseUrl
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1 --port 5173',
        url: 'http://127.0.0.1:5173',
        reuseExistingServer: !process.env.CI,
        env: {
          VITE_API_PROXY_TARGET: process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        },
      },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
