---
page: /portal
title: Client portal
routes: /portal, /portal/sites/:id, /portal/reports, /portal/invite/:token
---
The client's own view of their sites, made for a phone. A client contact sees only the sites
EESPL has shared with them, and on each site only the sections switched on for it and allowed by
their client role. Here they follow progress, read the daily reports, sign inspections, certify
bills, approve measurements, raise snags and comment. Everything they do tells the site's EESPL
team at once.

**Getting in (the invite)**
- EESPL's site team invites the client contact from the site's **Portal** tab and sends them a one-time link. The app sends no email or SMS: the link comes from a person at EESPL.
- The link opens **EESPL client portal** with "Welcome, <name>". **Email** is filled in and cannot be changed.
- **New password (10 characters or more)** and **Repeat it**: the same password twice. Not a common one, not the person's name or email, not one character repeated or a plain sequence.
- **Set password**: saves it. "Your password is set. Sign in with <email>." Then **Go to sign in** opens the login page.
- The link works once and lasts 7 days (the company can change this). A new invite stops the earlier link.

**The top bar (every portal page)**
- **EESPL · Client portal**: back to the list of sites.
- The client company's name with its initials.
- The bell: the notifications (see What happens next). Each opens the right site and tab.
- **Light** / **Dark**: the look; remembered for the person on every device.
- **My reports**: the problems the person reported and where each stands.
- **Sign out**: ends the session on this device.

**Home: the sites**
- "Hello, <name>", then one card per shared site: name, code and city, overall progress in % with a bar, **Last report** date and **Open snags**.
- Tap a card to open the site.
- "No sites are shared with you yet.": EESPL has not given this person a site, or has not switched the site on for the portal.

**A site**
- **← All sites**: back to the list.
- **Section** (on a phone, a drop-down) or the tabs: **Overview**, **Daily reports**, **Photos**, **Inspections & MOM**, **Drawings & documents**, **Billing**, **Snags**, **Measurements**, **Handover dates**. Only the sections EESPL switched on for the site and the client role allows are shown.

**Overview**
- **Overall progress** in %, the last report date, open snags and the count of work items at each stage.
- **By tower / floor**: the progress of each tower and floor.
- **Open meeting points for you**: the points of a meeting (MOM) given to the client. **Acknowledge** says "we have seen it"; then the point shows **acknowledged**. {perm: portal.approve}
- The 3D view of the building, when EESPL has made one.

**Daily reports**
- One card per report EESPL submitted (the last 120), newest first: date, weather, work done and the people on site by trade.
- Tap the date to open it: the work items with their stage and %, hindrances, the plan for tomorrow, material received, equipment, the photos, and the comments.
- **PDF**: downloads the report.

**Photos**
- The work photos EESPL chose to share, by date, each with its place and work step. Tap a photo to see it full size.
- **Area**: shows one place only (**All areas** for everything). Shown when photos come from more than one place.

**Inspections & MOM**
- **Inspections**: each inspection with its code, date, checklist, step and result (pass, fail, pass with remarks). Tap the code to read and write comments.
- **PDF**: downloads the inspection report.
- **Sign off**: on an inspection waiting for the client. Opens **Sign off <code>**: type **Your name**, draw the **Signature** on screen, press **Sign**. The inspection then shows **signed by <name>** and the site team is told. {perm: portal.approve}
- **Minutes of meeting**: each meeting with its points, who owns each point and its status. **PDF** downloads the minutes. **Acknowledge** on the open points given to the client. {perm: portal.approve}

**Drawings & documents**
- The drawings and documents EESPL shared ("From EESPL") and the ones the client uploaded ("Uploaded by you"), with the revision and date. **Download** opens the file.
- **Upload your drawing**: **Title**, then **Choose the drawing** (PDF, photo, DWG or DXF), then **Upload**. "Uploaded. EESPL has been told." {perm: portal.comment}

**Billing**
- **Overdue** (accounts and project manager roles): each bill past its due date, how much, since when, and where it is held on the client's side.
- **Due now**: the outstanding less the retention held until handover; **Total outstanding** with the retention in it; the amounts by age (0-30, 31-60, 61-90, 90+ days).
- **Retention held**, with the contract value and retention %.
- **RA bills**: each bill with its period, status, **Submitted**, **Certified** and **Net** amounts. Tap the code to see the lines and the comments. **PDF** downloads it.
- **Certify**: on a submitted bill. Opens **Certify <code>**: one box per billed line, filled with the billed quantity; lower it where less was done. **Remark** is optional. **Certify** sends it. The bill becomes "certified by client" and the site team is asked to confirm. {perm: portal.approve}
- **Reject**: on a submitted bill. Asks "Why are you rejecting <code>?"; the reason is required. The bill becomes "rejected by client" and the site team is told with the reason. {perm: portal.approve}
- **Tax invoices**: each invoice and credit note with its total, outstanding and days due. **PDF** downloads it.
- **Receipts**: the payments EESPL received, with the mode, reference and TDS.

**Measurements**
- The measurements EESPL sent for approval, one card per place: the sizes, the quantity and the status (**to approve**, **correction sent**, **approved**).
- **Approve**: accepts the line as measured. {perm: portal.approve}
- **Correct**: opens the correction. **Value to correct** (the size or the quantity), **metres** or **ft + in**, the **Correct value** (or **Feet** and **Inches**), **Remark (what you measured)**, then **Send the correction**. **Cancel** closes it. The old and new values are kept with the name and time; EESPL's billing accepts or disputes it. {perm: portal.approve}

**Handover dates**
- Each place (tower, floor, flat ...) with **Handover promised** and **Handed over**.
- The planning and project manager roles type the date they promise to hand the place over; it saves when they leave the box, and the site team is told. A place already handed over cannot be changed. {perm: portal.comment}
- When EESPL moved a date: "Moved by the applicator: <reason>", with the date the client had promised.

**Snags**
- **Raise a snag**: opens **Raise a snag**. **What is wrong?** (required), **Where** (a place on the site, or **Somewhere else (type below)** and then **Area**), **Details**, **Add photos** (camera on a phone). **Send to EESPL** sends it. {perm: portal.snag}
- Each snag: title, status (open, in progress, fixed, verified, closed), code, place, who raised it and when, and how many times it was reopened. Tap the title for the details, photos and comments.
- **Verify fixed**: on a snag EESPL marked fixed. It becomes verified. {perm: portal.snag}
- **Reopen**: on a fixed or verified snag. Asks "What is still wrong?"; the answer is required and added as a comment. The snag goes back to open. {perm: portal.snag}

**Comments**
- Under an opened daily report, inspection, RA bill or snag: the conversation with EESPL. **Write a comment**, then **Send**. EESPL's internal notes are never shown. {perm: portal.comment}

**My reports**
- **Report a problem**: type what you were doing and what went wrong, then **Send**. "Thank you: it is in the issue log as #<n>."
- The table: each report with its number, date, the problem, your words and its status (with the fix and "Live since" once fixed).

**Rules**
- The client role decides what each contact may do. As set by default: Project manager does everything; Planning sees progress, documents and sets handover dates; Site sees progress, signs inspections and raises snags; Billing approves measurements and certifies bills; Accounts sees bills and payments. EESPL can change these in Settings > Client roles.
- A button the client role does not allow is not shown: **Acknowledge** and **Sign off** need the right to sign inspections, **Certify** / **Reject** the right to certify bills, **Raise a snag** / **Verify fixed** / **Reopen** the right to raise snags. An inspection waiting for someone else shows "waiting for sign-off". Ask a colleague with that role.
- A certification is not final until EESPL confirms it. Only bills in "submitted" can be certified or rejected.
- You cannot certify more than was billed on a line.
- A measurement with a correction waiting for EESPL cannot be approved until EESPL answers.
- Everything done in the portal is recorded with the person's name and time.
- A client login opens only the portal. Staff addresses take it back to the portal.
- EESPL staff can preview a site as one client contact from the site's **Portal** tab, read-only. {perm: portal.manage}

**What happens next**
- Every sign-off, acknowledgement, certification, rejection, upload, measurement answer, handover date, snag and comment notifies the site's in-charge and team at EESPL.
- The client is notified when EESPL submits a daily report, submits an RA bill for certification, confirms their certification, asks for an inspection sign-off, shares a document, raises or updates a snag, comments, or moves a handover date.

**Hands off**
- Receives: the invite link and the site from EESPL's site team; reports, bills, inspections and measurements as EESPL sends them.
- Passes on: sign-offs, certifications, approvals, corrections, snags and comments to EESPL's site team.

**When it goes wrong**
- "This invite link has expired or was already used": ask EESPL's site team for a new invite.
- "The two passwords differ": type the same password in both boxes.
- "Your client role does not allow this (bill.certify)" (or inspection.sign, snag.raise, handover.edit, measurement.approve): another person on the client's side must do it.
- "This inspection is not waiting for your sign-off": it was signed already or EESPL withdrew the request. Refresh.
- "Draw the signature on screen": draw it before pressing **Sign**.
- "<code> is <status>" on a bill or snag: someone already acted on it. Refresh.
- "You cannot certify more than was billed": lower the quantity.
- "A correction on this line waits for our answer": wait for EESPL to answer the correction.
- "That place is not on this site": choose the place again.
- "Site not found" / "Not shown for this site": EESPL stopped sharing the site or that section.
- "<place>'s handover (received on <date>) is locked: it cannot be changed or deleted. Make a new revision or an addendum.": the place was already handed over.
