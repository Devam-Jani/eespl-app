// The visual tests (npm run test:visual): the main screens compared with their approved pictures,
// at 1440 and 390 px, dark and light, on the local production stack's training company (DEMO data).
//   BASE=https://training.localhost ENV_FILE=../.env.prod.local CHROME=<chromium> npm run test:visual
// UPDATE: add -- --update-snapshots after an approved change of the look.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.03, animations: "disabled", caret: "hide" } },
  use: {
    baseURL: process.env.BASE ?? "https://training.localhost",
    ignoreHTTPSErrors: true,
    launchOptions: process.env.CHROME ? { executablePath: process.env.CHROME } : {},
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    { name: "phone", use: { viewport: { width: 390, height: 844 } } },
  ],
});
