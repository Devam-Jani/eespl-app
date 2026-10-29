---
page: /payroll
title: Payroll & wages
routes: /payroll
---
Staff salaries and the wages of our own site labour. The monthly run makes a payslip for everyone
with a salary set, from the staff check-ins, with PF, ESI, PT, advances and loss of pay. Labour wages
are made from a site's muster roll. The page is headed **Payroll**. Salary figures are shown only
to the roles that may see salaries; the others see only **Labour wages**.

**On the page**
- **Monthly runs** (tab): one card per month, newest first, marked **draft** or **paid, locked**. Each payslip shows **Person** (with the days worked), **Days paid** (paid days / days in the month), **Gross**, **PF**, **ESI**, **PT**, **Advance** (recovered), **Net** and a **Total** row. {perm: payroll.view}
- **Month** (field): the month to compute. {perm: payroll.edit}
- **<person> LOP** (field): loss-of-pay days for each person with a salary. Leave blank for none. {perm: payroll.edit}
- **Compute <month>** (for example **Compute 2026-10**): makes the month's payslips, or computes them again with the LOP typed. {perm: payroll.edit}
- **Mark paid and lock**: on a draft month. Asks "Paid ₹... for <month>: bank reference?". Type the bank reference and press OK. The month becomes paid, locked. {perm: payroll.edit}
- **Payslip**: downloads the person's payslip PDF. {perm: payroll.view}
- **Salaries** (tab): every salary set, with **Person**, **From**, **Basic**, **HRA**, **Other**, **PF / ESI** and **Monthly CTC**. A person can have several rows: the latest one from a date applies from that date. {perm: payroll.view}
- **Set a salary**: opens the **Salary structure** form. {perm: payroll.edit}
- **Labour wages** (tab): pick a **Site** to see its wage payments: **Worker** (with the trade), **Period**, **Days**, **OT h**, **Wage due**, **Advances**, **Net** and paid or not.
- **From** and **To** (fields) and **Make wages from the muster roll**: make wage payments for the site and period from the muster roll. The button works once both dates are filled. {perm: payables.edit}
- **Mark paid**: marks one worker's wage payment paid in cash today. {perm: payables.edit}

**Salary structure (the form)** {perm: payroll.edit}
- **Person \***: the staff member. {perm: payroll.edit}
- **From**: the date the salary applies from (the 1st of this month unless you change it). Saving again for the same person and date changes that row. {perm: payroll.edit}
- **Basic (₹ a month) \***, **HRA**, **Other allowances**: the monthly amounts. {perm: payroll.edit}
- **PF** and **ESI (below the threshold)**: tick when they apply. ESI is only charged when the gross is below the ESI threshold. {perm: payroll.edit}
- **Save**: saves the salary and works out the monthly CTC (gross plus employer PF and ESI). {perm: payroll.edit}

**Rules**
- Worked days come from the staff check-ins. Leave and loss of pay are typed by hand. {perm: payroll.view}
- PF, ESI and PT use the rates in Settings > Finance. {perm: payroll.view}
- A salary advance is recovered in the next run, whole advances only; what does not fit waits for the next month. Approved travel claims are added to the payslip. {perm: payroll.view}
- A locked month cannot be computed again. {perm: payroll.view}
- Wages are made only for our own labour. Subcontractor workers are paid by their subcontractor.
- A worker's wages cannot be made twice for overlapping dates on the same site. Advances given to the worker on that site are taken off the wage.

**What happens next**
- **Compute**: the month is a draft. You can compute it again until it is locked. From the 25th, accounts sees "Payroll ... Not run yet" or "Still a draft" on My work until the month is locked. {perm: payroll.edit}
- **Mark paid and lock**: the month is locked and goes to the Tally export as a salary journal on the month's last day. {perm: payroll.edit}
- **Make wages from the muster roll**: the wage rows appear in the list as not paid. If no own worker has wages due in the period, nothing is added. {perm: payables.edit}

**Hands off**
- Receives: staff check-ins and travel claims (field tracking); the muster roll from site supervisors.
- Passes on: the locked payroll to the Tally export; salary cost to Site profit.

**When it goes wrong**
- "... is locked (paid)": the month was already paid and locked. It cannot be changed here.
- "LOP is more than the days in the month": lower the LOP days.
- "... is already locked": someone locked the month already. Reload the page.
- "The period ends before it starts": fix **From** and **To**.
- "...'s wages for part of this period are already made": wages for these dates already exist for that worker. Pick dates after the last period.
- "Already paid": the wage was marked paid already. Reload the page.
- **Payslip** shows an error above the page: the download failed. Read the message, reload the page and try again.
