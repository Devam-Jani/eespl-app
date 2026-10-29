---
page: /analytics/sites
title: Sites analytics
routes: /analytics/sites
---
**Sites analytics** shows how the open sites are doing against time: progress against the time used, the forecast end dates, the steps where work gets stuck, and the open snags. It reads the sites you may see. The worker refreshes the figures; the summary line says "as of" when.

**On the page**
- The summary line: "n sites · n delayed · n open snags · snags take n days to close on average · as of ...".
- **Region**, **Salesperson**, **Client type** (filters): narrow the sites. Each starts at "All ...". The Region and Salesperson lists only show when there is something to choose.
- **Site status** (filter): "Open sites" by default (active, planned, on hold). Pick one status to see only those sites.
- **Demo company (invented data)** (tick box): shows the training company's invented sites instead of the real ones. Only shown when demo data exists. {perm: dashboard.company}
- **⤓ Excel**: downloads every table of the page, with the filters applied, as one Excel file. The download is written to the audit log. {perm: reports.export}
- **Progress vs time elapsed** (chart): one dot per site; across, the share of the planned time used; up, the progress. Delayed sites are marked. Click a dot to open the site.
- **Stage bottlenecks: steps open longest** (chart): the steps that stay open longest, in days, with how many are open on how many sites. Click a bar to open the list of those records.
- **Planned vs forecast end** (table): start, target, forecast end, slip in days and progress per site. The first 15 rows show; **Show all n** shows the rest and **Show fewer** folds them again. Click the site in the first column to open it.
- **Snags by site** (table): open snags per site (first 10, then **Show all n**).

**Rules**
- A site is delayed when its planned end has passed, or when its progress is behind the time used by more points than the delay threshold of the analytics settings (15 points by default).
- Forecast = today + remaining % / the progress rate of the last 30 days. It needs 14 days of history and more than 0.05 % progress a day; otherwise no forecast is shown.
- The filters are kept in the page address, so a filtered view can be shared as a link and the back button works.

**What happens next**
- Nothing is changed from this page. A delayed site or a stuck step is followed up from the site page.

**Hands off**
- Receives: progress from the daily reports approved on site; stage steps and snags from the sites.
- Passes on: delayed sites and stuck steps to the site engineer and planning of that site.

**When it goes wrong**
- "Missing permission: dashboard.company or dashboard.site": your role cannot open this page. Ask the super admin.
- "not refreshed yet" in place of the date: the worker has not built the figures yet. Wait for the next refresh.
- "Nothing in this range.": no site matches the filters. Clear the filters.
