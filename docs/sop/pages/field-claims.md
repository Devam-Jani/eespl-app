---
page: /field/claims
title: Travel claims
routes: /field/claims, /field/claims/:id
mark: My claim this month so far
---
The monthly travel claim is made by the app from your days on My day: each day's km times your rate
per km on that date, plus the tolls, parking and other bills you add. On the 1st the past month's
claim is made ready; your manager approves the days, then accounts approve the month and it is paid
with that month's payroll.

**On the page**
- **Month** (field): shows only the claims of that month. Empty shows all months.
- **My claim this month so far**: builds (or updates) your claim for the current month from the
  days ended so far, so you can check it before the month ends.
- **⤓ Excel (<month>)**: downloads every claim of the chosen month (a CLAIMS sheet and a DAYS sheet). Shown once a month is picked. {perm: field.claims}
- The list: **Person**, **Month**, **Status**, **Km**, **Total**, **Flagged days** (red when above
  0). Press the person's name to open the claim. You see your own claims and those of the people
  you manage; accounts see all.
- Status: "this month so far" (draft), "with the manager" (ready), "with accounts" (approved by
  the manager), "approved (locked)".

**A claim (/field/claims/:id)**
- The heading: "Travel claim: <person>, <month>" with the status, then the km, "days ₹ + tolls and
  parking ₹ = total", the flagged days in red, the manager, who approved, and "accounts: <name>,
  paid with payroll <month>" once approved.
- **⤓ Excel**: downloads this claim.
- **Approve the days**: the person's manager (or the director or office admin) approves all the
  days. Not shown on your own claim.
- **Approve the month (accounts)**: locks the claim and books it into this month's payroll. Shown after the manager approved. {perm: field.claims_approve}
- The days: **Date**, **Stops** (press to open the day on the map), **Km** ("road" or "tracked",
  "est." when estimated, "was n km: <reason> (<who>)" when changed), **₹/km**, **Amount**,
  **Flags** (in red).
- **Edit** (on each day, for the manager before approving): type the **Km** and the **Reason**,
  then **Save**. The amount is worked again at that day's rate.
- **Tolls, parking and other costs**: the bills added, with their photo.
- Add a bill (the person, before the manager approves): **Date**, **Kind** (**Toll**,
  **Parking**, **Other**), **Amount**, **Note**, **Bill photo** (camera or PDF; it shows "Bill photo
  ✓"), then **Add**. **Add** stays grey until the date, the amount and the photo are given.

**Rules**
- The claim is built from ended days only. A day with no rate per km on its date is flagged "No
  rate per km on this date (Settings > Field tracking)" and counts ₹0.
- Only people with travel reimbursement turned on, and who gave consent on My day, have a claim.
- There is no submit button: on the 1st the past month's claim becomes "with the manager" by
  itself, and the person and the manager are notified.
- Tolls and parking are added by the person only, while the claim is "this month so far" or "with
  the manager". The date must be in the claim's month.
- The manager can change a day's km only with a reason; the original km, the reason and who changed
  it stay on the line. A day the manager edited is not rebuilt later.
- After **Approve the days** nothing can be edited or added. After **Approve the month
  (accounts)** the claim is locked.
- Flags never reject a day by themselves; the manager decides.

**What happens next**
- On the 1st: the person gets "Your travel claim for <month> is ready" (information); the manager
  gets a to-do **Approve**. Not approved in 3 days, it escalates to the director.
- **Approve the days**: accounts get a to-do **Approve** ("approved by the manager: Approve the
  month"). Not approved in 5 days, it escalates to the director.
- **Approve the month (accounts)**: the claim is paid with the current payroll month as a
  reimbursement, outside the salary's gross. The accounts to-do closes.

**Hands off**
- Receives: the person's ended days from My day; the rates per km and the manager from the office
  admin (Settings > Field tracking).
- Passes on: the person to the manager (days to approve), the manager to accounts (month to
  approve), accounts to payroll.

**When it goes wrong**
- "No travel claim: not eligible for travel reimbursement, or no consent": ask the office admin to
  turn on travel reimbursement for you, and give your consent on My day.
- "Tolls and parking are added by the person, before the manager approves": the claim is already
  approved, or it is not yours.
- "The date is not in <month>": add the bill to the claim of the month it belongs to.
- "Give the reason for the change": write the reason before **Save**.
- "The claim is already approved by the manager": days cannot be changed any more.
- "The person's manager edits the days" / "The person's manager (or the director) approves the
  days": only the manager named in the person's tracking profile does this.
- "The manager approves the days first": accounts can approve only after the manager.
- "Not your claim to see" / "Claim not found": the claim is not yours or your team's.
- A day's km look wrong: open the day from **Stops**, check the flags and the legs. The manager can
  edit the km, or choose road or tracked km on the day's map.
