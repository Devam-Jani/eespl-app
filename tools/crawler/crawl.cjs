// The nightly check: signs in to the training company as each role's DEMO user and opens every
// page of its menu (and the first record of each list), recording console errors, failed requests,
// blank screens, buttons that do nothing and pages slower than 2 s. Findings go to the issue log
// book ("found by the nightly check") when REPORT_URL and CRAWLER_TOKEN are set, and to OUT.
//
//   BASE=https://training.localhost ENV_FILE=../../.env.prod.local node crawl.cjs
//
// env: BASE (the training company), DEMO_USER_PASSWORD or ENV_FILE (read from it, never printed),
// ROLES (comma list; default every DEMO role and the client), REPORT_URL (the main app's
// /api/issues/nightly), CRAWLER_TOKEN, OUT (a JSON file), SLOW_MS (2000), CLICKS (1: try buttons),
// DETAILS (1: open the first record of a list), CHROME (a Chromium to use), WIDTH (1600).
// Only the training company: it is rebuilt every night, so trying buttons there changes nothing real.
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = (process.env.BASE || "https://training.localhost").replace(/\/$/, "");
const SLOW_MS = Number(process.env.SLOW_MS || 2000);
const CLICKS = process.env.CLICKS !== "0";
const DETAILS = process.env.DETAILS !== "0";
const WIDTH = Number(process.env.WIDTH || 1600);
const STAFF = ["director", "office_admin", "planning", "billing", "accounts", "sales", "estimator", "site_engineer", "site_supervisor", "store_purchase", "site_receiver"];
const ROLES = (process.env.ROLES || [...STAFF, "client"].join(",")).split(",").map((r) => r.trim()).filter(Boolean);
const EMAIL = (role) => (role === "client" ? "demo-client-pm@example.com" : `demo-${role.replace(/_/g, "-")}@demo.invalid`);
// buttons never pressed: they would sign out, delete, send or decide something (even in training)
const UNSAFE = /sign out|clear|log ?out|delete|remove|archive|reject|approve|cancel|close|send|submit|save|post|pay|issue|confirm|reset|import|upload|download|export|print|lock|dispatch|mark|finish|end day|check.?(in|out)|start|stop|×|✕/i;

function password() {
  if (process.env.DEMO_USER_PASSWORD) return process.env.DEMO_USER_PASSWORD;
  const file = process.env.ENV_FILE;
  if (!file) throw new Error("Set DEMO_USER_PASSWORD or ENV_FILE");
  const m = fs.readFileSync(file, "utf8").match(/^DEMO_USER_PASSWORD=(.*)$/m);
  if (!m) throw new Error(`DEMO_USER_PASSWORD is not in ${file}`);
  return m[1].trim().replace(/^["']|["']$/g, "");
}

const pathOf = (u) => {
  try {
    return new URL(u).pathname;
  } catch {
    return u;
  }
};

// what a client must never be sent: our costs and margins, places (GPS), another client's records
const STAFF_ONLY = /(^|_)(costs?|margins?|markup|profit|purchase_rate|lat|lng|latitude|longitude|gps|accuracy_m)(_|$)/i;
function staffOnly(value, path = "", out = [], clients = new Set()) {
  if (Array.isArray(value)) value.forEach((v, i) => staffOnly(v, `${path}[${i}]`, out, clients));
  else if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      if (STAFF_ONLY.test(k) && v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length)) out.push(`${path}.${k}`);
      if (k === "client_id" && v !== null) clients.add(v);
      staffOnly(v, `${path}.${k}`, out, clients);
    }
  }
  return { out, clients };
}

async function crawlRole(browser, role, pw, findings, timings) {
  const ctx = await browser.newContext({ viewport: { width: WIDTH, height: 1000 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();
  let here = "/login";
  const add = (kind, error, extra = {}) => findings.push({ role, kind, page: here, error: String(error).slice(0, 1500), ...extra });
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/Failed to load resource: the server responded with a status of (401|403|404|409|422)/.test(t)) return; // the page says why
    if (/favicon|ResizeObserver/.test(t)) return;
    add("console error", t);
  });
  page.on("pageerror", (e) => add("page crash", `${e.name}: ${e.message}`, { stack: e.stack }));
  const clientIds = new Set();
  page.on("response", async (r) => {
    const u = r.url();
    if (!u.includes("/api/")) return;
    if (r.status() >= 500) {
      add("failed request", `HTTP ${r.status()} ${r.request().method()} ${pathOf(u)}`, { status_code: r.status(), request_id: r.headers()["x-request-id"] || null });
      return;
    }
    // a client login: nothing staff-only in any answer the portal gets
    if (role !== "client" || !(r.headers()["content-type"] || "").includes("json")) return;
    const body = await r.json().catch(() => null);
    const { out } = staffOnly(body, "", [], clientIds);
    if (out.length) add("staff-only data in the portal", `${r.request().method()} ${pathOf(u)} sent ${out.slice(0, 5).join(", ")}`);
    if (clientIds.size > 1) add("another client's data in the portal", `${pathOf(u)}: records of ${clientIds.size} clients`);
  });
  page.on("requestfailed", (r) => {
    const u = r.url();
    if (!u.startsWith(BASE) || /aborted|ERR_ABORTED/.test(r.failure()?.errorText || "")) return; // a page left mid-load
    add("failed request", `${r.failure()?.errorText} ${r.method()} ${pathOf(u)}`);
  });

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[type="email"]', EMAIL(role));
  await page.fill('input[type="password"]', pw);
  await page.click('button:has-text("Sign in")');
  try {
    await page.waitForURL((u) => !u.pathname.endsWith("/login"), { timeout: 30000 });
  } catch {
    add("cannot sign in", `The DEMO ${role} login did not open the app`);
    await ctx.close();
    return;
  }
  await page.waitForLoadState("networkidle").catch(() => {});
  const portal = new URL(page.url()).pathname.startsWith("/portal");
  // the menu's pages (every group opened; the portal: its home and each site)
  for (let i = 0; i < 20; i++) {
    const closed = page.locator("aside.sidebar .nav-toggle[aria-expanded='false']").first();
    if (!(await closed.count())) break;
    await closed.click().catch(() => {});
  }
  const links = await page.evaluate((p) => {
    const sel = p ? ".portal-main a[href^='/portal'], .portal-top a[href^='/portal']" : "aside.sidebar a[href^='/']";
    return [...new Set([...document.querySelectorAll(sel)].map((a) => a.getAttribute("href")))];
  }, portal);
  const queue = [...new Set([portal ? "/portal" : "/my-work", ...links])];
  const seen = new Set();
  while (queue.length) {
    const path = queue.shift();
    if (seen.has(path) || seen.size > 120) continue;
    seen.add(path);
    here = path;
    const t0 = Date.now();
    await page.goto(`${BASE}${path}`, { waitUntil: "networkidle", timeout: 60000 }).catch((e) => add("page did not load", e.message));
    await page.waitForFunction(() => !document.body.innerText.includes("Loading…"), null, { timeout: 30000 }).catch(() => add("still loading", "The page still said Loading… after 30 s"));
    const ms = Date.now() - t0;
    timings.push({ role, page: path, ms });
    if (ms > SLOW_MS) add("slow page", `The page took ${(ms / 1000).toFixed(1)} s to open (over ${SLOW_MS / 1000} s)`, { ms });
    const state = await page.evaluate(() => {
      const main = document.querySelector("main") || document.body;
      return { text: main.innerText.trim().length, crash: !!document.querySelector(".page-crash"), path: location.pathname };
    });
    if (role === "client") {
      // every site and every tab of the portal; no cost, margin or place on screen
      const more = await page.evaluate(() => {
        const sites = [...document.querySelectorAll("a[href^='/portal/sites/']")].map((a) => a.getAttribute("href").split("?")[0]);
        const tabs = [...document.querySelectorAll("select.tab-select option")].map((o) => `${location.pathname}?tab=${o.value}`);
        return [...sites, ...tabs];
      });
      for (const m of more) if (!seen.has(m)) queue.push(m);
      const words = await page.evaluate(() => (document.querySelector("main")?.innerText || "").match(/(margin|our cost|cost price|purchase rate|latitude|longitude)/i)?.[0] || null);
      if (words) add("staff-only data in the portal", `The page shows "${words}"`);
    }
    if (state.crash) add("page crash", "The page showed 'This page hit a problem'");
    else if (state.text < 15) add("blank screen", "The page showed nothing");
    if (state.path !== path && !path.includes("?")) here = `${path} → ${state.path}`;
    // the first record of a list (one level deep)
    if (DETAILS && !/\/\d+/.test(path)) {
      const first = await page
        .$$eval("main table tbody tr a[href^='/'], main .card a[href^='/']", (as) => as.map((a) => a.getAttribute("href")).filter((h) => /\/\d+/.test(h)).slice(0, 1))
        .catch(() => []);
      for (const f of first) if (!seen.has(f)) queue.push(f);
    }
    // buttons that do nothing: pressed, nothing changed (no request, no change on the page, no dialog)
    if (CLICKS) {
      // by label, found again before each press (a press may redraw or leave the page)
      const labels = await page
        .$$eval("main button", (bs) =>
          bs
            .filter((b) => b.offsetParent !== null && !b.disabled && b.type !== "submit")
            .map((b) => (b.getAttribute("aria-label") || b.innerText || "").replace(/\s+/g, " ").trim()),
        )
        .catch(() => []);
      const tryThese = [...new Set(labels)].filter((l) => l && !UNSAFE.test(l)).slice(0, 12);
      for (const label of tryThese) {
        const b = page.locator("main button:visible", { hasText: label }).first();
        if (!(await b.count().catch(() => 0))) continue;
        const before = await page.evaluate(() => {
          window.__changes = 0;
          window.__obs?.disconnect();
          window.__obs = new MutationObserver((m) => (window.__changes += m.length));
          window.__obs.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
          return location.href;
        });
        let requests = 0;
        const onReq = () => (requests += 1);
        page.on("request", onReq);
        let popup = false;
        const onDialog = (d) => {
          popup = true;
          void d.dismiss().catch(() => {});
        };
        page.on("dialog", onDialog);
        await b.click({ timeout: 3000 }).catch(() => {});
        await page.waitForTimeout(700);
        page.off("request", onReq);
        page.off("dialog", onDialog);
        const after = await page.evaluate(() => ({ changes: window.__changes, href: location.href })).catch(() => ({ changes: 1, href: "" }));
        if (!popup && !requests && after.changes === 0 && after.href === before) add("dead button", `"${label.slice(0, 60)}" did nothing when pressed`, { action: `pressed "${label.slice(0, 60)}"` });
        if (after.href !== before) {
          await page.goto(`${BASE}${path}`, { waitUntil: "networkidle", timeout: 60000 }).catch(() => {});
        } else {
          await page.keyboard.press("Escape").catch(() => {});
        }
      }
    }
  }
  await ctx.close();
}

(async () => {
  const pw = password();
  const launch = { args: ["--ignore-certificate-errors"] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  const browser = await chromium.launch(launch);
  const findings = [];
  const timings = [];
  const started = Date.now();
  for (const role of ROLES) {
    try {
      await crawlRole(browser, role, pw, findings, timings);
    } catch (e) {
      findings.push({ role, kind: "crawler error", page: "?", error: String(e).slice(0, 500) });
    }
    console.error(`${role}: ${timings.filter((t) => t.role === role).length} pages, ${findings.filter((f) => f.role === role).length} findings`);
  }
  await browser.close();
  // one finding per problem (the same on several roles: one, with each role)
  const grouped = new Map();
  for (const f of findings) {
    const key = [f.kind, f.page.replace(/\/\d+/g, "/:id"), f.error.replace(/\d+/g, "#")].join("|");
    const g = grouped.get(key) || { ...f, roles: [] };
    if (!g.roles.includes(f.role)) g.roles.push(f.role);
    grouped.set(key, g);
  }
  const summary = {
    base: BASE,
    at: new Date().toISOString(),
    minutes: +((Date.now() - started) / 60000).toFixed(1),
    roles: ROLES.length,
    pages_opened: timings.length,
    slowest: [...timings].sort((a, b) => b.ms - a.ms).slice(0, 10),
    by_kind: [...grouped.values()].reduce((m, f) => ((m[f.kind] = (m[f.kind] || 0) + 1), m), {}),
    findings: [...grouped.values()],
  };
  if (process.env.OUT) fs.writeFileSync(process.env.OUT, JSON.stringify(summary, null, 1));
  console.log(JSON.stringify({ ...summary, findings: summary.findings.length, slowest: summary.slowest.slice(0, 5) }, null, 1));
  if (process.env.REPORT_URL && process.env.CRAWLER_TOKEN && summary.findings.length) {
    const body = {
      findings: summary.findings.slice(0, 500).map((f) => ({
        kind: "error",
        page: f.page.split(" ")[0],
        action: f.action || null,
        error: `${f.kind}: ${f.error}`,
        status_code: f.status_code || null,
        request_id: f.request_id || null,
        stack: f.stack || null,
        browser: "Nightly check (Chromium)",
        words: `${f.roles.join(",")}: ${f.kind}`,
      })),
    };
    const r = await fetch(process.env.REPORT_URL, { method: "POST", headers: { "Content-Type": "application/json", "X-Crawler-Token": process.env.CRAWLER_TOKEN }, body: JSON.stringify(body) });
    console.error(`reported to the issue log: HTTP ${r.status}`);
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
