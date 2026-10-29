---
page: /analytics/profitability
title: Profitability
routes: /analytics/profitability
mark: ⤓ Excel
---
**Profitability** shows the margin of the sites, clients, systems and salespeople, and the margin quoted against the margin made on finished sites. Margin = (billed − cost) / billed, before GST. The page shows cost, so it needs tender.margin as well as a dashboard permission.

**On the page**
- **Region**, **Salesperson**, **Client type**, **Site status** (filters): narrow the sites. **Site status** starts at "Open sites".
- **Demo company (invented data)** (tick box): shows the training company's invented data. Only shown when demo data exists. {perm: dashboard.company}
- **⤓ Excel**: downloads every table of the page as one Excel file. Written to the audit log. {perm: reports.export}
- The yellow note "Staff salary is not included in cost (needs payroll.view)." shows when your role cannot see payroll. The margins are then higher than the real ones.
- Three bar charts: margin by client, by system and by salesperson (top 10 each), with the billed amount beside each bar.
- **Margin by site** (table): first 15 rows, **Show all n** for the rest. Click a site to open it.
- **Quoted vs actual margin, finished sites** (chart and table): **Quoted margin %** against **Actual margin %** per finished site. The quoted margin comes from the won tender's costed BOQ lines. A site's system is the one with the largest quoted amount.

**Rules**
- Cost includes staff salary only for roles that can see payroll. {perm: payroll.view}

**What happens next**
- Nothing is changed from this page.

**Hands off**
- Receives: billing, purchase cost, labour cost and (with payroll) salary.
- Passes on: sites or systems that lose margin, to the estimator and the director for the next tenders.

**When it goes wrong**
- "Cost and margin need tender.margin": your role does not see cost. This page is not for you.
- "Missing permission: dashboard.company or dashboard.finance": your role cannot open this page.
