// The pages a record's page leads to beyond the menu: its tabs, the sections under "More" and the
// pages under "Open" (a site's Measure and bill, AutoCAD takeoff, methodology ...). The options of
// the tab menus are read from the page; this turns them into the paths to visit. No dependencies,
// so the tests can load it.

/**
 * @param {string} pathname the record's page, e.g. /sites/12
 * @param {string[]} values the options' values of its tab menus (a section key, or a path for Open)
 * @returns {string[]} the paths to visit, each once
 */
function extraPages(pathname, values) {
  const out = [];
  for (const v of values) {
    if (!v) continue;
    const path = v.startsWith("/") ? v : `${pathname}?tab=${encodeURIComponent(v)}`;
    if (!out.includes(path)) out.push(path);
  }
  return out;
}

/** The record pages whose tabs and Open menu are followed (a site, a tender). */
function followsTabs(pathname) {
  return /^\/(sites|tenders)\/\d+$/.test(pathname);
}

// A PC that sleeps mid-crawl freezes the crawler: the page open then "takes" as long as the sleep
// (a /payroll of 1014 s), the requests in flight fail with net::ERR_NETWORK_IO_SUSPENDED, and the
// first pages after waking are slow while Docker wakes up. Such a page is opened again, not reported.
const GAP_MS = 30000; // the crawler's 1 s heartbeat stopped this long: it was not running
const PLAUSIBLE_MS = 120000; // a page open is cut at 60 s (goto) + 30 s (still loading)
const WAKE_SETTLE_MS = 120000; // a slow page this soon after a sleep: the PC was still waking

/** The longest wait between consecutive heartbeat ticks (wall-clock ms), 0 with fewer than two. */
function longestGap(ticks) {
  let gap = 0;
  for (let i = 1; i < ticks.length; i++) gap = Math.max(gap, ticks[i] - ticks[i - 1]);
  return gap;
}

/**
 * Why a page's open time (or failure) is the PC's sleep and not the page's, or null.
 * @param {object} o
 * @param {number} o.ms the open time by the wall clock (Date.now)
 * @param {number} [o.monoMs] the same by the monotonic clock (performance.now); on a PC whose
 *   monotonic clock stops in sleep, the wall clock runs ahead
 * @param {number} [o.maxGapMs] the longest heartbeat gap while the page opened
 * @param {string[]} [o.errors] what went wrong while it opened (failed requests, console errors)
 * @param {number} [o.sinceWakeMs] time since the last sleep ended (Infinity: none seen)
 * @param {number} [o.slowMs] the slow-page limit
 * @returns {string|null}
 */
function sleptDuring({ ms, monoMs, maxGapMs = 0, errors = [], sinceWakeMs = Infinity, slowMs = 2000 }) {
  if (errors.some((e) => /ERR_NETWORK_IO_SUSPENDED/.test(e))) return "the network was suspended (the PC slept)";
  if (maxGapMs > GAP_MS) return `the crawler stood still for ${Math.round(maxGapMs / 1000)} s (the PC slept)`;
  if (monoMs !== undefined && ms - monoMs > GAP_MS) return `the clock jumped ${Math.round((ms - monoMs) / 1000)} s (the PC slept)`;
  if (ms > PLAUSIBLE_MS) return `${Math.round(ms / 1000)} s is longer than a page open can take (the PC slept)`;
  if (ms > slowMs && sinceWakeMs < WAKE_SETTLE_MS) return "slow just after the PC woke up";
  return null;
}

module.exports = { extraPages, followsTabs, longestGap, sleptDuring, GAP_MS, PLAUSIBLE_MS, WAKE_SETTLE_MS };
