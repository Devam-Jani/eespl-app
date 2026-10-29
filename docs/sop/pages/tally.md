---
page: /tally
title: Tally export
routes: /tally
mark: Day book (Excel)
---
The vouchers of a date range, ready to import into TallyPrime (Gateway › Import › Vouchers). It is
download only: nothing is sent anywhere. The table previews each voucher with **Date**, **Type**,
**Number**, **Ledger**, **Debit** and **Credit**, one row per ledger entry.

**On the page**
- **From** and **To** (fields): the date range. It starts on the 1st of this month and ends today.
- **include exported** (tick): also take vouchers that were exported before. Leave it off to export only new ones.
- **Export n voucher(s) as XML**: downloads the TallyPrime XML of the vouchers in the preview and marks them exported. It is greyed out when there are no vouchers. {perm: finance.export}
- **Day book (Excel)**: downloads the same vouchers as an Excel day book (Date, Type, Number, Party, Ledger, Debit, Credit, Narration). It marks nothing exported.
- **Ledger names in Tally**: one field for each ledger the vouchers use (sales, GST, TDS, bank, petty cash and so on). Type the name exactly as in Tally. Clients and vendors map to party ledgers of the same name.
- **Save ledger names**: saves the ledger names (party ledger mappings already set are kept). The message "Ledger names saved." appears.

**What goes in**
- Sales and credit notes: tax invoices that are issued.
- Purchase: vendor and subcontractor bills that are approved, partly paid or paid.
- Receipt: client receipts.
- Payment: vendor payments that are paid (not those waiting for approval).
- Journal and Contra: approved petty cash entries and advances.
- Journal: a locked payroll month, dated the month's last day.

**Rules**
- Every voucher must balance (debits equal credits) or the export stops.
- After an export, the vouchers are skipped next time unless **include exported** is ticked. Tick it only to export again on purpose, or Tally gets them twice.
- A party name in Tally must match the client or vendor name in the app.

**What happens next**
- **Export**: the file `eespl-tally-<from>-<to>.xml` downloads. The message "Exported n voucher(s); they are marked exported." appears and the preview empties. Import the file in TallyPrime.

**Hands off**
- Receives: invoices and receipts from billing and accounts; vendor bills and payments from Payables; petty cash; the locked payroll.
- Passes on: the XML to the accountant's TallyPrime.

**When it goes wrong**
- "The range ends before it starts": fix **From** and **To**.
- "Vouchers that do not balance: ...": those vouchers have a rounding or tax error. Open them in the app, fix them, then export again.
- **Day book (Excel)** shows an error (for example "The range ends before it starts"): the download failed. Check the dates and try again.
- Tally refuses a ledger on import: the ledger name differs from Tally. Fix it under **Ledger names in Tally**, tick **include exported** and export the range again.
