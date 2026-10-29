---
page: /analytics/purchase
title: Purchase analytics
routes: /analytics/purchase
---
**Purchase analytics** shows what we spend with each supplier and on each product category, how the PO rate of the top products moves month by month, and freight as a share of the material used per site. Spend is taken from approved POs, before GST.

**On the page**
- **From**, **To** (dates), **Region**, **Site status** (filters): narrow the POs and sites. Empty dates: the 12 months up to today.
- **Demo company (invented data)** (tick box): shows the training company's invented data. Only shown when demo data exists. {perm: dashboard.company}
- **⤓ Excel**: downloads every table of the page as one Excel file. Written to the audit log. {perm: reports.export}
- **Spend by supplier (PO value before GST)** (chart): the 12 largest suppliers.
- **Spend by product category** (chart).
- **PO rate trend, top 20 products by spend** (chart): pick the product in **Product**. The line is the average PO rate after discount, per month, in ₹ per the product's unit. "No POs in this range." when there is none.
- **Freight as % of material used, per site** (table): material used, freight and freight %. First 12 rows, **Show all n** for the rest.

**Rules**
- The freight table shows cost. Without tender.margin it stays empty with the note "Needs tender.margin (it shows cost)."

**What happens next**
- Nothing is changed from this page.

**Hands off**
- Receives: approved POs from purchase, material issued on site, freight bills.
- Passes on: a rising price or a high freight share, to take up with the supplier.

**When it goes wrong**
- "Missing permission: dashboard.company or dashboard.purchase": your role cannot open this page.
- "No POs in this range.": no approved PO for that product between the dates. Widen the dates.
