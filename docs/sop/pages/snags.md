---
page: /snags
title: Snags
routes: /snags
mark: New snag
---
Snags are points to fix on a site: raised by the client in the portal, or by our team here. The page
lists the snags of every site you can see. A snag moves from open to in progress, fixed, verified
and closed, and the client follows it in the portal.

**On the page**
- **New snag**: opens the form for a snag raised by our team. {perm: site.update}
- **Site** (filter): **All sites** or one site.
- **Status** (filter): **Any status**, open, in progress, fixed, verified, closed.
- **Raised by** (filter): **Raised by anyone**, **Raised by the client**, **Raised by staff**.
- **Open only** (tick box, shown when no status is chosen): ticked at first. It shows open, in
  progress and fixed snags (fixed ones still wait to be verified).
- Columns: **Code**, **Site** (press it to open the site), **Snag** (title and area), **Raised**
  ("client" badge or "staff", and the date), **Assigned**, **Due**, **Status** (with "reopened n×"
  when the client sent it back).
- Press a row to open the snag.

**The New snag form** {perm: site.update}
- **Site**: one of your sites. {perm: site.update}
- **Title** (needed), **Area** (where on the site), **Details**. {perm: site.update}
- **Photos**: **Choose photos** adds one or more "before" photos. {perm: site.update}
- **Save**: makes the snag (code SNG-...), status open, and opens it. The client users of the site
  who follow snags in the portal are notified. {perm: site.update}

**The snag window**
- The title, status, area, who raised it and when, the details and the photos ("before" and
  "after"). A client snag that is fixed shows "waiting for the client to verify".
- The photo, person, due date and status buttons below show only to roles that may change the
  site; others see the snag and its comments only.
- **Add "after" photo**: opens the camera to add a photo of the fixed work. {perm: site.update}
- **Assigned to**: choose a staff member of the site (the in-charge and the members). They are
  notified "assigned to you". {perm: site.update}
- **Due**: the date it should be fixed by. {perm: site.update}
- The status buttons change with the status: {perm: site.update}
- **Start work** (open): moves it to in progress. {perm: site.update}
- **Mark fixed** (open or in progress): moves it to fixed. The client is told "fixed: please check
  and verify". {perm: site.update}
- **Verified** (fixed, raised by staff only): moves it to verified. {perm: site.update}
- **Back to in progress** (fixed): reopens the work. {perm: site.update}
- **Close** (verified): closes it. {perm: site.update}
- A closed snag has no buttons.
- Comments at the bottom: **Write a comment** and **Send**. Tick **internal note** to keep it from
  the client; an internal note shows an "internal" badge.

**Rules**
- An "after" photo must be attached before a snag can be marked fixed.
- A snag raised by the client is verified (or reopened) by the client in the portal, not here. When
  the client reopens it, the "reopened" count goes up.
- A snag can be assigned only to an active staff member of that site.
- Every status change and every new snag is shown to the client users of the site in the portal.
- A comment that is not an internal note is shown to the client and the client is notified. Every
  comment, internal or not, notifies the site's staff.
- Issues from the Issue log that are shared with the client also appear here as staff snags.

**What happens next**
- The person assigned sees it in their notifications and opens it from there.
- After **Mark fixed**, the client checks the work in the portal and verifies it, or sends it back.
  A staff snag is verified by our team with **Verified**, then closed with **Close**.

**Hands off**
- Receives: snags from the client (portal), from our team, and issues shared with the client from the
  Issue log.
- Passes on: the fixed snag to the client for verification; the assignment to the site staff member.

**When it goes wrong**
- "Attach an 'after' photo before marking it fixed": press **Add "after" photo** first, then
  **Mark fixed**.
- "<code> cannot go from <status> to <status>": that move is not allowed (for example, a client snag
  that is fixed can only go back to in progress here). Refresh the page and use the buttons shown.
- "Assign it to an active staff member of this site": the person is not on the site any more. Choose
  someone from the list, or have them added to the site.
- "Missing permission: site.update on <site code>": you can see the snag but not change it. Ask the
  site engineer or supervisor of that site to do it.
- "That place is not on this site": the chosen place belongs to another site.
- "Snag not found" or "Site not found": the snag is on a site you are not allocated to.
