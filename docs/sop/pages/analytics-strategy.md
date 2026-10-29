---
page: /analytics/strategy
title: Strategy: win more sites
routes: /analytics/strategy
mark: Win / loss
---
**Strategy** helps to win more sites: where tenders drop out between lead and order, why we lose, how our prices sit against the rate library, and which past clients to call. It reads leads and tenders; the salesperson filter narrows it to one person's work.

**On the page**
- **Tender funnel**, **Win / loss**, **Pricing position** (tabs): switch the view. The tab is kept in the page address.
- **Repeat clients** (tab): revenue by client, company-wide. {perm: dashboard.company}
- **From**, **To** (dates), **Region**, **Salesperson**, **Client type** (filters): apply to every tab. Empty dates: the 12 months up to today.
- **Demo company (invented data)** (tick box): shows the training company's invented data. Only shown when demo data exists. {perm: dashboard.company}
- **⤓ Excel** (on each tab): downloads that tab's figures as an Excel file, with the filters applied. Written to the audit log. {perm: reports.export}
- The note at the bottom: how much historic data the app holds (imported historic sites, rate-library lines from past BOQ files, tenders won or lost).

**Tender funnel tab**
- **Leads → tenders → submitted → won** (chart): the count and value at each step. Click a step to open the list of those leads or tenders. Under it: the lost count and value, and the win rate (won ÷ (won + lost)).
- **By segment** (card): pick **Segment**: **Total**, **Month**, **Salesperson**, **Client type**, **Source** or **Region**. The table shows **Leads**, **Tenders**, **Submitted**, **Won** and **Win rate** per segment, with the conversion % beside each count. Click a count to open those records.

**Win / loss tab**
- The line: tenders decided in the range, won, and the win rate.
- **Win rate by ...** (one chart per segment: client type, project size, waterproofing system, region, salesperson): bars with "n won / n lost". Click a bar to open those decided tenders.
- **Why we lose** (chart): the lost reasons, with the tender value and the number of leads lost for the same reason. Click a bar to open those lost tenders. Under it, "Lost to:" lists the competitors named and how often.

**Pricing position tab**
- **Our quoted rate ÷ rate-library median, won vs lost** (chart): per system, the median ratio on **Won tenders** and on **Lost tenders**. Above 1.00 means we quoted above the median. The note lists how many lines were counted (won / lost).

**Repeat clients tab** {perm: dashboard.company}
- The line: billed in the range, the part from repeat clients (two or more sites or won tenders), its share, and how many repeat clients. {perm: dashboard.company}
- **Top 10 clients by billed value** (chart): ↻ marks a repeat client. Click a bar to open that client's invoices. {perm: dashboard.company}
- **No enquiry in 12 months: worth a call** (table): past customers (a site or a won tender) with no lead or tender in the last 12 months, with type, sites and last enquiry. {perm: dashboard.company}

**Rules**
- A tender counts as decided when it is won or lost; open tenders do not change the win rate.
- The pricing position only uses rate-library items that have a median rate.

**What happens next**
- Nothing is changed from this page. Use the lists to plan calls and pricing.

**Hands off**
- Receives: leads and tenders from sales and the estimator, lost reasons recorded on tenders, the rate library.
- Passes on: the "worth a call" list to sales; the pricing position to the estimator and the director.

**When it goes wrong**
- "Missing permission: dashboard.company or dashboard.sales": your role cannot open this page.
- "Missing permission: dashboard.company" on the repeat clients: that tab is company-wide and only for management.
- "Pick a segment: month, salesperson, client type, source or region.": choose a **Segment** to fill the table.
