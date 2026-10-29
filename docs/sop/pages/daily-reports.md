---
page: /daily-reports
title: Daily reports
routes: /daily-reports, /my-site/:id, /my-site/:id/report
---
The daily progress report (DPR) of each site. The **Daily progress reports** page lists the
reports of the last 14 days for your sites and warns about active sites that have not sent one.
On the phone, the site supervisor works from **My site today** and sends the work done place by
place from **Today's report**.

**On the page: Daily progress reports (list)**
- The banner at the top: "n active site(s) without a DPR for <day>:" followed by the site codes,
  or "Every active site sent its DPR for <day>." in green. Before 8 pm it checks yesterday; from
  8 pm it checks today. A site counts as missing when it is active, has started, and has no report
  for that day, or only a draft. Tap a site code to open that site on its daily report tab.
- The table: **Date**, **Site**, **Status**, **Weather**, **By** (who submitted), **Photos**
  (how many). Tap the site code to open the site's daily report tab.
- **Status** shows the report's state as stored: draft (saved, not sent), submitted (waiting for
  the site engineer), acknowledged (approved), returned (sent back for correction).
- The page has no buttons of its own. Writing, approving and returning a report happen on the
  site's daily report tab (Sites > the site > daily report) and on the phone screens below.
- On the site's daily report tab, **Approve** marks a submitted report approved, and **Return**
  asks "Return to the supervisor: what needs correcting?" and sends it back with your note
  (at least 3 characters). {perm: dpr.approve, dpr.edit}

**On the page: My site today (/my-site/:id)**
- The site code and name, then five steps. Each step shows **To do · n** (orange) with the open
  items under it, or **Done** (green). The labels are also shown in Gujarati and Hindi.
- **1. Attendance**: opens the site's labour tab to mark today's attendance. It is "To do" until
  at least one worker is marked for today.
- **2. Deliveries**: opens **Deliveries at site** filtered to this site, unconfirmed. It counts
  deliveries sent and expected by today that are not yet confirmed.
- **3. Issue material to areas**: opens the site's material tab. It is "To do" when material came
  into the site store in the last 3 days and nothing was issued to the areas since.
- **4. Work done, with photos**: opens **Today's report**. It is "To do" while today's report is
  not submitted, and also for each report the site engineer returned.
- **5. Snags**: opens **Snags** for this site.
- The counts come from your own My work list. A step whose items are not on your list (for a
  site supervisor, the snags) always shows **Done**: open the step to check.
- **Ask for material**: opens the material request form for this site ("By area and thickness:
  the app works out the kg and the bags."). {perm: material_request.create}

**On the page: Today's report (/my-site/:id/report)** {perm: dpr.edit}
- **Back to my site**: back to **My site today**. {perm: dpr.edit}
- The chip **n of m done**: places reported today out of the places due today. The count is kept
  on this phone; on another phone it starts again from 0. {perm: dpr.edit}
- The places listed are those whose current step is under way, held up, or due to start by
  today. If there are none: "Nothing to report today. No step on this site is under way or due
  today." {perm: dpr.edit}
- The card shows the place and **Step x of y · <step name>**. **Change** opens the list of today's
  places; tap one to report it. Places already sent show "sent". {perm: dpr.edit}
- **Work done today**: pick one of **<step name> done**, **Part done** or **No work today**. {perm: dpr.edit}
- **Length measured (ft + in)** (field): feet in the first box, inches in the second. The app
  saves it in metres. Not asked for **No work today**. {perm: dpr.edit}
- **Photos (at least 1)**: tap **Camera** to take photos. Up to 6 per place. Not asked for
  **No work today**. {perm: dpr.edit}
- The send button says what is missing first: **Choose the work done to send**, **Fix the length to send**, **Add a photo to send**. When everything is there it reads **Send today's report**. {perm: dpr.edit}
- **Send today's report**: adds this place's line to today's report (it replaces an earlier line
  for the same place and step), then uploads the photos. "<place>: sent." shows and the next
  place comes up. {perm: dpr.edit}
- Sending the last place of the day also submits the report to the site engineer. {perm: dpr.edit}

**Rules**
- A report can be written for today or an earlier day, never for a future day.
- A report can be changed while it is a draft or returned. Once submitted or approved it is locked.
- Photos can only be added while the report is a draft.
- Submitting needs the "Work done today" text, which is typed on the site's daily report tab. The phone screen has no box for it (see "When it goes wrong"). {perm: dpr.edit}
- Each send from the phone also blanks the weather, work done, hindrances and plan for tomorrow typed on the site's daily report tab. Type those last, on the tab, just before **Submit DPR**. {perm: dpr.edit}
- Only the site engineer of the site approves or returns. The office can too when it holds daily reports for every site. {perm: dpr.approve, dpr.edit}
- No signal: the report is kept on the phone with its photos ("Saved on the phone; it sends when the signal is back") and sent, oldest first, when the phone is back online or the page is opened again. Do not clear the browser data before it has gone. {perm: dpr.edit}

**What happens next**
- Submit: the site engineer gets "Daily report of <date> for <site>: approve or return." If it is
  not approved or returned within 24 hours, planning is told. The site's clients see "Daily report
  of <date> for <site>" on the portal.
- The first report on an area tells planning that work started there, and moves the site to
  "ongoing" on the site status board.
- A line on a new area (not in the quotation) tells planning to quote or approve that area.
- Approve: the quantity on each line is added to the progress of that place's work item, once.
  An item that reaches 100 % becomes ready to bill.
- Return: the supervisor who submitted gets "Daily report of <date> returned: <note>", and it sits
  on their My work as "Correct" until it is sent again.

**Hands off**
- Receives: the day's places and steps from planning's schedule.
- Passes on: the site supervisor sends the report to the site engineer; the approved report feeds
  progress, the ready-to-bill list, the client portal and planning.

**When it goes wrong**
- "Write the work done before submitting": the report has no "Work done today" text. On the phone this happens on the last place of the day, because the phone screen has no box for it. Open the site's daily report tab, type **Work done today**, add the line for the last place if it is missing, and press **Submit DPR**. {perm: dpr.edit}
- "A DPR cannot be written for a future day": check the phone's date.
- "The DPR of <date> is already submitted" (or "already acknowledged"): the report is locked. Ask
  the site engineer to return it if it must change.
- "The DPR is already submitted": photos cannot be added once the report has left draft, also
  when it was returned. Say so in the line text and tell the site engineer.
- "The site engineer approves daily reports" / "The site engineer returns daily reports": only the site engineer of that site can do this. {perm: dpr.approve, dpr.edit}
- "The DPR is <status>": someone already approved or returned it. Reload the page.
- "That survey area is not on this site": the line names an area from another site's survey.
- "Saved on the phone; it sends when the signal is back" stays on screen: the report is still
  waiting on the phone. Open the page again with signal. If it still does not go, tell the site
  engineer; a refusal reason is not shown on this screen.
