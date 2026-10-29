---
page: /reports
title: Reports
routes: /reports
mark: File this week's now
---
**Reports** holds the weekly management summaries and the PDF reports to download. The management summary is filed every Monday at 8 am (IST) and announced in the bell. Nothing is emailed yet.

**On the page**
- **File this week's now**: files this week's management summary at once, without waiting for Monday. A week is filed only once: if this week's summary is already there, nothing new is made and the page says "This week's summary is already filed: it is in the list below."
- **Download** (card): the PDF reports. The whole card is shown only to roles that may export. {perm: reports.export}
- **Management summary (PDF)**: today's management figures, the open alerts and the delayed sites. Written to the audit log. {perm: reports.export}
- **Receivables (PDF)**: who owes what, today. Written to the audit log. {perm: reports.export}
- **Sales pipeline (PDF)**: the open leads and tenders. Written to the audit log. {perm: reports.export}
- **Site** (list, "Site status report for…"): pick an active site; the button **Site status (PDF, no costs)** then appears. It downloads the site's status report without any cost, safe to share. {perm: reports.export}
- **Weekly management summaries** (table): one row per week filed ("Week of ..."), with its first figures. **PDF** downloads that week's summary as it was filed.

**Rules**
- A filed weekly summary is a snapshot: it does not change when the data changes later.
- Margins appear in the PDFs only for roles that see cost. {perm: tender.margin}
- The PDFs are made from the real company, never from the demo company.

**What happens next**
- When a summary is filed (on Monday or with **File this week's now**), every active user whose role has the management dashboard gets "Management summary for the week of <date>" in the bell, linking to this page.

**Hands off**
- Receives: the figures of every module.
- Passes on: the summary to management; the site status PDF to the client or the site team.

**When it goes wrong**
- "Missing permission: dashboard.company": only management opens this page.
- "Missing permission: reports.export": your role cannot download the PDFs.
- "Report not found": the weekly report is no longer there. Reload the page.
- "None filed yet.": no week has been filed. Press **File this week's now**.
