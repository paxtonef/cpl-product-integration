import { defineConfig, devices } from '@playwright/test'

// Definitive acceptance: real PI-05, real PostgreSQL, real VIR, real PGDR --
// this config assumes those are already running (see docs/build/
// PI_06_FRONTEND_CANDIDATE_EVIDENCE_v0.md for the exact process/setup used
// during this build) and only starts the frontend dev server itself.
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --port 5173',
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
