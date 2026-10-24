// The new look's main screens, compared with their approved pictures (dark and light). What changes
// day to day (dates, counts, the live 3D picture) is masked; the layout, colours and type are not.
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const password = (() => {
  if (process.env.DEMO_USER_PASSWORD) return process.env.DEMO_USER_PASSWORD;
  const m = readFileSync(process.env.ENV_FILE ?? "../.env.prod.local", "utf8").match(/^DEMO_USER_PASSWORD=(.*)$/m);
  return (m?.[1] ?? "").trim().replace(/^["']|["']$/g, "");
})();

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button:has-text("Sign in")');
  await page.waitForURL((u) => !u.pathname.endsWith("/login"));
}

async function settle(page: Page, path: string, theme: "dark" | "light") {
  await page.goto(path, { waitUntil: "networkidle" });
  await page.waitForFunction(() => !document.querySelector(".page-skeleton") && !document.body.innerText.includes("Loading…"), null, { timeout: 30_000 });
  await page.evaluate((t) => (document.documentElement.dataset.theme = t), theme);
  await page.addStyleTag({ content: "*{transition:none!important;animation:none!important} .toasts{display:none!important}" });
  await page.waitForTimeout(400);
}

const masks = (page: Page) => [
  page.locator("canvas"),
  page.locator(".nav-count"),
  page.locator(".bell-count, .badge-count, [class*='bell'] .count"),
  page.locator(".home-head"),
  page.locator(".kpi-value, .kpi-note, .mb-value"),
  page.locator(".golive-banner, .go-live-banner"),
  page.locator("td"),
];

const SCREENS: { name: string; who: string; path: string }[] = [
  { name: "dashboard", who: "demo-director@demo.invalid", path: "/dashboard" },
  { name: "site-3d", who: "demo-director@demo.invalid", path: "/sites/13?tab=3d" },
  { name: "phone-report", who: "demo-site-engineer@demo.invalid", path: "/my-site/13/report" },
  { name: "how-it-works", who: "demo-director@demo.invalid", path: "/help/how-it-works" },
  { name: "portal", who: "demo-client-pm@example.com", path: "/portal" },
];

for (const s of SCREENS) {
  for (const theme of ["dark", "light"] as const) {
    test(`${s.name} (${theme})`, async ({ page }) => {
      await signIn(page, s.who);
      await settle(page, s.path, theme);
      await expect(page).toHaveScreenshot(`${s.name}-${theme}.png`, { mask: masks(page), fullPage: false });
    });
  }
}
