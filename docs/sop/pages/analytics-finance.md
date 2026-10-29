---
page: /analytics/finance
title: Finance analytics
routes: /analytics/finance
mark: ⤓ Excel
---
**Finance analytics** shows billing, money received and cost by month, the cash expected over the next 8 weeks, the days sales outstanding (DSO) and who owes what. Without dates it covers the 12 months up to today.

**On the page**
- **From** and **To** (dates): the range of months. Empty: the 12 months up to today.
- **Demo company (invented data)** (tick box): shows the training company's invented data. Only shown when demo data exists. {perm: dashboard.company}
- **⤓ Excel**: downloads every table of the page, with the dates applied, as one Excel file. Written to the audit log. {perm: reports.export}
- **Billed vs received vs cost by month** (chart): **Billed (net of GST)** and **Received** bars per month. Click a month to open the records behind it.
- The **Cost** line on the same chart. {perm: tender.margin}
- **Cash flow, next 8 weeks** (chart): **Expected receipts** (the due part of invoices by due date, retention left out) against **Supplier payments** (approved supplier bills by due date).
- **Days sales outstanding** (chart): DSO = receivable at month end / invoiced in the last 3 months x 90.
- **Outstanding by client** (chart and table): the 12 largest balances as bars, and the table below (first 10, **Show all n** for the rest). Click a client to open its invoices.

**Rules**
- Amounts are before GST unless the label says otherwise.
- Without tender.margin the cost line is not shown.

**What happens next**
- Nothing is changed from this page. The Receivables PDF is on **Reports**.

**Hands off**
- Receives: invoices and receipts from billing and accounts; supplier bills from payables.
- Passes on: the clients to chase, to accounts and the director.

**When it goes wrong**
- "Missing permission: dashboard.company or dashboard.finance": your role cannot open this page.
- "Nothing in this range.": no data between the two dates. Widen the dates.
