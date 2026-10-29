---
page: /settings/field
title: Field tracking settings
routes: /settings/field
mark: Save
---
Who is tracked (from Start day to End day only, with their consent), who is paid travel per km,
their vehicle, manager, weekly off and home, the company holidays, and the general tracking
settings. Labour and clients are never listed or tracked. Every change is written to the audit
log.

**On the page**
- The people table: **Person**, **Tracked**, **Travel per km**, **Vehicle**, **Manager**, **Weekly off**, **Rate today**, **Home**, **Consent**. Each change in a row is saved at once.
- **Tracked**: tick to track the person's route while their day is on.
- **Travel per km**: tick if the person is eligible for travel reimbursement.
- **Vehicle**: **Bike**, **Car** or **Other**.
- **Manager**: the person who approves their travel claims and sees their day. **—** for none.
- **Weekly off**: a day of the week, or **none**. A day started on the weekly off is flagged for the manager, not blocked.
- **Rate today**: the rate per km in force today, or **—**.
- **Home**: **approved**, **to approve** (in orange) when the person asked for a home or a new home, or the status.
- **Consent**: the date the person gave consent, or "not given".
- The person's name: opens or closes their details row.

**A person's details**
- **Rate per km**: the rates with their vehicle and dates ("from … to …", or "(in force)").
- **Vehicle**, **Rate per km**, **Valid from**: a new rate from a date.
- **Add the rate**: saves the new rate. The rate in force until then ends the day before. The history is kept. The form is cleared afterwards, also when the rate was refused.
- **Home location**: a map with the approved home (⌂) and the home asked for (?).
- **Approve**: shown when a home is asked for. The asked-for place becomes the approved home.
- **Not approved**: refuses it. The old home stays, if there was one.

**Company holidays**
- The holidays with their date and name. **Remove** deletes one at once (no question asked).
- **Date**, **Holiday**: a new holiday. **Add**: saves it.
- A day started on a holiday or on the person's weekly off is flagged for the manager (never blocked).

**General**
- **Consent version (a new one asks everyone again)**: change it and everyone must give consent again.
- **Day ends by itself at (IST)**: HH:MM. A day still on at this time is ended.
- **Site circle (m)**: 20 to 5000. Inside this distance a check-in counts as at the site.
- **Start / end flagged beyond home (m)**: 50 to 50000. A day started or ended further from home is flagged.
- **Gap flagged after (min)**: 5 to 600. A gap in the route longer than this is flagged.
- **Raw points kept (days)**: 1 to 3650. The route points are deleted after this.
- **Day summaries and claims kept (years)**: 1 to 30.
- **Map tiles URL** (must start with https://) and **Map credit**: the map shown in the app.
- **Save**: saves the general settings. The page reloads; no "saved" message is shown.

**Rules**
- Only roles with the field admin right open this page.
- Only office employees are tracked or reimbursed.
- A person cannot be their own manager.
- A new rate must start after every rate already saved for that person.

**What happens next**
- A tracked person is asked for consent and their route is recorded from Start day to End day.
- Each month the km and rates make the travel claim. The manager approves it, then accounts.

**Hands off**
- Receives: requests for home locations from field staff.
- Passes on: the tracking and rates the travel claims are built from (to the managers and accounts).

**When it goes wrong**
- "Only office employees are tracked or reimbursed": that person is a labour or client user.
- "A person is not their own manager": pick another manager.
- "A rate already starts on or after that date": choose a later **Valid from**. Type the rate again; the form was cleared.
- "No home location waiting for approval": someone already decided it. The page reloads.
- "That date is already a holiday": the date is listed already.
- A time not written as HH:MM, a number out of range or a tiles URL without https:// is refused next to the field.
