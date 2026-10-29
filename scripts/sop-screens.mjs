// The SOP pictures (docs/sop): each role's pages on the training company, logged in as that role's
// DEMO user, the button being explained in a red box. Office roles 1600 px wide, site and phone roles
// 390 px (the role file's `width`). Rows that are not DEMO on the pages listing people are blurred.
//
//   SOP_BASE=https://training.example.com SOP_PASSWORD=... [SOP_ADMIN_EMAIL=... SOP_ADMIN_PASSWORD=...] \
//     node scripts/sop-screens.mjs data/sop/screens [role ...]
//
// Run from the repository (it reads docs/sop); playwright comes from frontend/node_modules. The
// super admin has no DEMO user on the training company: SOP_ADMIN_* is its login there. No password
// is printed.
import { mkdirSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(join(process.cwd(), "frontend", "package.json"));
const { chromium } = require("playwright");

const BASE = process.env.SOP_BASE;
const PASSWORD = process.env.SOP_PASSWORD;
if (!BASE || !PASSWORD) throw new Error("Set SOP_BASE and SOP_PASSWORD");
const [out = "data/sop/screens", ...only] = process.argv.slice(2);
const DIR = "docs/sop";
const PEOPLE = new Set(["/admin/users", "/admin/audit", "/admin/user-import", "/settings/team", "/field/team", "/settings/security", "/admin/roles"]);
const DEMO_LOGIN = { client: "demo-client-pm@example.com" };

function front(text) {
  const m = text.replace(/\r\n/g, "\n").match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) return [{}, text];
  const meta = Object.fromEntries(
    m[1]
      .split("\n")
      .map((l) => l.split(/:(.*)/s).map((x) => x.trim()))
      .filter((x) => x.length > 1),
  );
  return [meta, m[2]];
}

const pages = {};
for (const f of readdirSync(join(DIR, "pages"))) {
  const [meta] = front(readFileSync(join(DIR, "pages", f), "utf8"));
  if (meta.page) pages[meta.page] = meta;
}
const roles = [];
for (const f of readdirSync(DIR)) {
  if (!f.endsWith(".md") || f === "README.md") continue;
  const [meta, body] = front(readFileSync(join(DIR, f), "utf8"));
  if (!meta.role || meta.role === "index") continue;
  const list = body
    .split("\n")
    .filter((l) => l.trim().startsWith("@page "))
    .map((l) => l.trim().slice(6).trim());
  roles.push({ role: meta.role, width: Number(meta.width || 1600), pages: list });
}

function slug(page) {
  return page.replace(/^\/+|\/+$/g, "").replaceAll("/", "-").replaceAll(":", "") || "home";
}

async function login(page, email, password) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 });
}

async function mark(page, label) {
  if (!label) return false;
  const target = page
    .getByRole("button", { name: label, exact: true })
    .or(page.getByRole("link", { name: label, exact: true }))
    .or(page.getByRole("tab", { name: label, exact: true }))
    .first();
  if (!(await target.isVisible().catch(() => false))) return false;
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) return false;
  await page.evaluate((b) => {
    const d = document.createElement("div");
    d.className = "sop-mark";
    Object.assign(d.style, {
      position: "absolute",
      left: `${b.x + window.scrollX - 5}px`,
      top: `${b.y + window.scrollY - 5}px`,
      width: `${b.width + 10}px`,
      height: `${b.height + 10}px`,
      border: "3px solid #e00000",
      borderRadius: "6px",
      zIndex: 99999,
      pointerEvents: "none",
    });
    document.body.appendChild(d);
  }, box);
  return true;
}

async function blurPeople(page) {
  await page.evaluate(() => {
    for (const row of document.querySelectorAll("tbody tr, li, .card-row, .list-row")) {
      const t = row.textContent || "";
      if (t.trim() && !/demo/i.test(t)) row.style.filter = "blur(5px)";
    }
  });
}

const browser = await chromium.launch();
const made = {};
for (const r of roles) {
  if (only.length && !only.includes(r.role)) continue;
  const phone = r.width < 800;
  const ctx = await browser.newContext({ viewport: { width: r.width, height: phone ? 844 : 900 }, deviceScaleFactor: phone ? 2 : 1, isMobile: phone, hasTouch: phone });
  const page = await ctx.newPage();
  const admin = r.role === "super_admin";
  const email = admin ? process.env.SOP_ADMIN_EMAIL : (DEMO_LOGIN[r.role] ?? `demo-${r.role.replaceAll("_", "-")}@demo.invalid`);
  const password = admin ? process.env.SOP_ADMIN_PASSWORD : PASSWORD;
  if (!email || !password) {
    console.log(`${r.role}: no login, skipped`);
    continue;
  }
  try {
    await login(page, email, password);
  } catch {
    console.log(`${r.role}: login failed, skipped`);
    await ctx.close();
    continue;
  }
  mkdirSync(join(out, r.role), { recursive: true });
  let n = 0;
  let marked = 0;
  for (const p of r.pages) {
    if (!p.startsWith("/") || p.includes(":")) continue;
    try {
      await page.goto(`${BASE}${p}`, { waitUntil: "networkidle", timeout: 45000 });
      await page.waitForTimeout(600);
      if (PEOPLE.has(p) || admin) await blurPeople(page);
      if (admin) await page.evaluate(() => document.querySelectorAll(".app-me, .app-avatar").forEach((e) => (e.style.filter = "blur(5px)")));
      if (await mark(page, pages[p]?.mark)) marked += 1;
      await page.screenshot({ path: join(out, r.role, `${slug(p)}.png`) });
      n += 1;
    } catch (e) {
      console.log(`${r.role} ${p}: ${String(e).split("\n")[0]}`);
    }
  }
  made[r.role] = { shots: n, marked };
  console.log(`${r.role}: ${n} screenshots, ${marked} with the button marked`);
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(made));
