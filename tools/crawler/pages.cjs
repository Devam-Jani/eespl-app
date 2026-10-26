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

module.exports = { extraPages, followsTabs };
