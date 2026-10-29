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

/** The DEMO pool site's Measure and bill page (its id changes with each nightly rebuild). */
async function measurePath(page: Page): Promise<string> {
  await page.goto("/sites", { waitUntil: "networkidle" });
  await page.getByPlaceholder("Search code, name, client or city").fill("DEMO-POOL");
  await page.locator("tr.clickable").filter({ has: page.locator("code", { hasText: /^DEMO-POOL$/ }) }).first().click();
  await page.waitForURL(/\/sites\/\d+/);
  return `${new URL(page.url()).pathname.match(/^\/sites\/\d+/)![0]}/measure?ask=no`;
}

/** The first measurement sheet opened from the Sheets tab: the page brings it up below the top bar. */
async function openSheet(page: Page) {
  await page.getByRole("tab", { name: /Sheets/ }).click();
  await page.getByRole("button", { name: /^MS-DEMO-POOL-01/ }).click();
  await expect(page.locator("#m-sheet")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(800); // the smooth scroll to the sheet
}

/** A modal (the slip bill's) over the page: it covers the top bar, never the other way round. */
async function openModal(page: Page) {
  await page.getByRole("tab", { name: /Sheets/ }).click();
  await page.getByRole("button", { name: "Bill from a slip" }).click();
  await expect(page.getByRole("dialog", { name: "Bill from a site slip" })).toBeVisible();
}

/** The DEMO terrace site's material request (the site's id changes with each nightly rebuild). */
async function askPath(page: Page): Promise<string> {
  const id = await page.evaluate(async () => {
    const t = await (await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" })).json();
    const r = await (await fetch("/api/sites?q=DEMO-TERRACE", { headers: { Authorization: `Bearer ${t.access_token}` } })).json();
    return (r.items as { id: number; code: string }[]).find((x) => x.code === "DEMO-TERRACE")!.id;
  });
  return `/my-site/${id}/material`;
}

/** Asked for more than the estimate, scrolled to the bottom: the warning, the reason and Send clear the tabs. */
async function askOver(page: Page) {
  await page.locator("select").first().selectOption({ label: "Nodular (kg)" });
  await page.locator("select").nth(1).selectOption({ index: 1 });
  await page.locator('input[type="number"]').first().fill("5000");
  await expect(page.locator(".alert-warn .ask-formula")).toBeVisible({ timeout: 15_000 });
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.waitForTimeout(300);
  const tabs = await page.locator(".app-tabs").boundingBox();
  for (const el of [page.locator("textarea"), page.getByRole("button", { name: "Send to planning" })]) {
    const box = await el.boundingBox();
    expect(box && tabs && box.y + box.height <= tabs.y).toBe(true);
  }
}

const SCREENS: { name: string; who: string; path: string | ((page: Page) => Promise<string>); then?: (page: Page) => Promise<void>; phoneOnly?: boolean }[] = [
  { name: "dashboard", who: "demo-director@demo.invalid", path: "/dashboard" },
  { name: "site-3d", who: "demo-director@demo.invalid", path: "/sites/13?tab=3d" },
  { name: "phone-report", who: "demo-site-engineer@demo.invalid", path: "/my-site/13/report" },
  { name: "how-it-works", who: "demo-director@demo.invalid", path: "/help/how-it-works" },
  { name: "portal", who: "demo-client-pm@example.com", path: "/portal" },
  // the Measure and bill page and the five heaviest pages moved to the shared components
  { name: "measure", who: "demo-billing@demo.invalid", path: measurePath },
  // a sheet and a modal on that page: the top bar never draws over them
  { name: "measure-sheet", who: "demo-billing@demo.invalid", path: measurePath, then: openSheet },
  { name: "measure-modal", who: "demo-billing@demo.invalid", path: measurePath, then: openModal },
  { name: "quotations", who: "demo-director@demo.invalid", path: "/quotations" },
  { name: "surveys", who: "demo-director@demo.invalid", path: "/surveys" },
  { name: "measurement-book", who: "demo-director@demo.invalid", path: "/measurements" },
  { name: "deliveries", who: "demo-director@demo.invalid", path: "/deliveries" },
  // the phone's material request over the estimate, scrolled to the bottom: nothing under the tabs
  { name: "phone-ask-material", who: "demo-site-engineer@demo.invalid", path: askPath, then: askOver, phoneOnly: true },
  // Prompt 39: the sidebar's new name and tag, Users with the invite status, Issues with Raise an issue
  { name: "users", who: "demo-office-admin@demo.invalid", path: "/admin/users" },
  { name: "issues", who: "demo-director@demo.invalid", path: "/issues" },
];

for (const s of SCREENS) {
  for (const theme of ["dark", "light"] as const) {
    test(`${s.name} (${theme})`, async ({ page }, info) => {
      test.skip(!!s.phoneOnly && info.project.name !== "phone", "a phone page");
      await signIn(page, s.who);
      await settle(page, typeof s.path === "string" ? s.path : await s.path(page), theme);
      await s.then?.(page);
      await expect(page).toHaveScreenshot(`${s.name}-${theme}.png`, { mask: masks(page), fullPage: false });
    });
  }
}

// signed out: the login page with the product name, its tag and the company line; never "ERP"
for (const theme of ["dark", "light"] as const) {
  test(`login (${theme})`, async ({ page }) => {
    await settle(page, "/login", theme);
    await expect(page.locator(".login-brand small")).toHaveText(/Site & Tender app/);
    await expect(page.locator("body")).not.toContainText(/\bERP\b/);
    await expect(page).toHaveScreenshot(`login-${theme}.png`, { fullPage: false });
  });
}
