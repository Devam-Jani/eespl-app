// My site today: the supervisor's My work items of the one site that is open. An item names its
// site (site_id, from the site supervisor's list) or, failing that, its link names it exactly
// ("/my-site/12?step=..." is site 12, never site 1). An item in two role lists counts once.
type Item = { key: string; link: string; site_id?: number };

/** The site a link points at: /sites/<id>, /my-site/<id> or ?site=<id>; null when none. */
export function linkSite(link: string): number | null {
  const m = /\/(?:my-site|sites)\/(\d+)(?=[/?#]|$)/.exec(link) ?? /[?&]site=(\d+)(?=[&#]|$)/.exec(link);
  return m ? Number(m[1]) : null;
}

export function siteItems<T extends Item>(sections: { items: T[] }[], siteId: number): T[] {
  const seen = new Set<string>();
  return sections
    .flatMap((s) => s.items)
    .filter((i) => (i.site_id !== undefined ? i.site_id === siteId : linkSite(i.link) === siteId))
    .filter((i) => !seen.has(i.key) && !!seen.add(i.key));
}
