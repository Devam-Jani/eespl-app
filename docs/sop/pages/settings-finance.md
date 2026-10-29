---
page: /settings/finance
title: Finance settings
routes: /settings/finance
mark: Save
---
The company-wide finance rules: the invoice number prefix, the SAC code, the three-way match
tolerance, the payment approval limit, the bill photo limit for petty cash, PF, ESI, TDS and
professional tax. Billing, payables and payroll see them; only the company settings right changes
them. Every save is written to the audit log.

**On the page**
- **Invoice prefix (e.g. <example>)**: up to 6 letters, digits or dashes. The label shows how an invoice number will look, for example "<prefix>/26-27/0001".
- **Works contract SAC**: 4 to 8 digits, printed on bills.
- **Three-way match tolerance %**: 0 to 50. A vendor bill whose quantity or rate differs from the GRN or PO by more is flagged.
- **Payment approval limit (₹)**: a payment above this needs a role with the payables approve right. Below it, the payment is marked paid at once.
- **Bill photo required above (₹)**: a petty-cash expense above this needs a bill photo.
- **PF %**, **PF wage cap (₹)**, **ESI threshold (₹ gross)**, **ESI employee %**, **ESI employer %**: the payroll deductions.
- **TDS by vendor type (JSON)**: the TDS rules per vendor type, written as JSON.
- **Professional tax slabs (JSON; default Gujarat)**: the professional tax slabs, written as JSON.
- **Save**: saves all the fields. "Saved." shows. {perm: settings.company}
- Without the company settings right the boxes are greyed and there is no **Save**.

**Rules**
- The invoice number must stay within 16 characters.
- A JSON box is read when you leave it. If the JSON is not valid, the box is not taken and the old rules are saved; nothing warns you. Check the text carefully. {perm: settings.company}

**What happens next**
- New invoices use the new prefix. New vendor bills, payments, petty-cash expenses and payroll runs use the new limits and rates. Documents already made keep theirs.

**Hands off**
- Receives: the rates and limits from the accountant and the director.
- Passes on: the rules billing, payables, petty cash and payroll work under.

**When it goes wrong**
- "The invoice number would exceed 16 characters": shorten the prefix.
- A prefix with other characters, a SAC that is not 4 to 8 digits, or a percent out of range is refused next to the field.
- "Payments above ₹<limit> need payables.approve": (on Payables) the payment is above the limit set here; an approver must approve it.
- "A bill photo is required above ₹<limit>": (on Petty cash) attach the bill photo.
