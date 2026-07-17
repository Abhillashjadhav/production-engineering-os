// Browser-level verification harness: REAL frontend (production build via
// `next start`) proxying to the REAL backend (uvicorn) — no mocks anywhere
// (PD-V3-10). Locally the pre-installed Chromium is used via
// PLAYWRIGHT_CHROMIUM_PATH when the packaged browser build is absent; CI
// installs the matching browser and leaves the variable unset.
import { defineConfig, devices } from "@playwright/test";

const chromiumPath = process.env.PLAYWRIGHT_CHROMIUM_PATH;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    ...(chromiumPath ? { launchOptions: { executablePath: chromiumPath } } : {}),
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: /responsive\.spec\.ts/,
    },
    {
      // the device profile supplies the mobile viewport/UA; Chromium is
      // forced because it is the only installed engine (documented seam)
      name: "mobile-chromium",
      use: { ...devices["iPhone 12"], browserName: "chromium" },
      testMatch: /responsive\.spec\.ts/,
    },
  ],
  webServer: [
    {
      // E2E_PYTHON lets the local run use the repo venv; CI installs the
      // backend into the system interpreter and leaves it unset
      command:
        "cd ../backend && ${E2E_PYTHON:-python3} -m uvicorn pm_evals_api.app:app --host 127.0.0.1 --port 8100",
      url: "http://127.0.0.1:8100/api/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: { PYTHONPATH: "src" },
    },
    {
      command: "cd ../frontend && npx next start --hostname 127.0.0.1 --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
      timeout: 60_000,
      env: { BACKEND_URL: "http://127.0.0.1:8100" },
    },
  ],
});
