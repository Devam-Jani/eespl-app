---
page: /field
title: My day (check-in)
routes: /field, /field/days/:id
mark: Start day
---
My day records your working day for attendance and travel: you start the day when you leave home,
check in at each site, vendor, godown or client office with your location (and a selfie at a site),
and end the day at home. The road km between your stops make your monthly travel claim. It is made
for the phone. The location is recorded only between **Start day** and **End day**, and only after
you give your consent. On a phone, site roles open it from the **My day** tab at the bottom.

**Before the first day**
- "You are not set up for field tracking. The office admin sets who is tracked (Settings › Field
  tracking).": nothing to do on this page until the office admin turns tracking on for you.
- **Location tracking: your consent**: what is recorded, why, who sees it, how long it is kept and
  where. Read it and press **I agree (version n)**. Without consent you can still use the rest of
  the app; nothing is tracked and no travel claim is made.
- When the text changes, the page asks again ("What we record has changed since you agreed ...").

**On the page**
- **Start day**: takes your location and starts the day. The day ends by itself at the set time
  (21:00 by default) if you forget **End day**.
- After the start: "Day started <time>", and "· started n m/km from home" when your home is
  approved. "Recording while this page is open: ... point(s) waiting to be sent / all points sent".
- **Check in** (card, shown when you are not checked in anywhere):
  - The kind: **Site**, **Vendor**, **Godown**, **Client office**, **Other**.
  - **Site** (field): your sites, the nearest first, with the distance ("· no pin" when the site
    has no location yet).
  - **Where** (field, for the other kinds): the vendor, godown or office name. Required for
    **Other**.
  - **Take the selfie (front camera)**: required at a site. It turns into "Selfie taken: retake".
  - **Check in here**: takes your location and records the check-in. At a site it also records
    your attendance at that site for payroll.
  - **Why are you outside the site circle?**: appears when you are farther from the site's pin than
    its radius. Write the reason and press **Check in here** again.
- While checked in: "At <place> since <time>", in red "· n m from the pin" if you were outside.
  - **Check out (selfie)**: opens the camera, then checks you out with the photo.
  - **Check out without a selfie**: checks you out with your location only.
  - Outside the circle the app asks for the reason in a box ("The reason:"). Cancel leaves you
    checked in.
- The list of today's stops with times, minutes and "· outside the circle" in red.
- **End day** (shown when you are not checked in): takes your location, sends the waiting points
  and ends the day. Then the card shows "Road km", "tracked km", which one the claim uses, and the
  day's flags.
- **The day on the map**: opens the day's map (below).
- **Today's route**: tick today's sites (only sites with a pin are listed) and press **Suggest the
  order**. The app orders them by the shortest road route from home and back. **↑** / **↓** move
  a site; **Go to site** opens the directions in your map app. The line under it gives the road km
  and the driving minutes, back home included.
- **Home location: <state>** (fold-out): "approved", "waiting for the office admin", "not
  approved, pick again" or "not set".
  - Tap the map to pick your home, or **Use my location** standing at home.
  - **Ask for approval**: sends the place to the office admin ("Sent for approval."). A change of
    an approved home needs approval again; the old home counts until then.
- At the bottom: when you gave consent and the version, **Withdraw consent** and **My travel
  claims** (for people with travel reimbursement).
- **Withdraw consent**: asks "Withdraw your consent? Tracking stops now (an open day ends) and no
  travel claim is made from here on." OK stops all tracking.

**The day on the map (/field/days/:id)**
- The heading: the person and the date, start and end times ("(ended by itself)" when the day
  ended at the set time), road km, tracked km and which one the claim uses, with the reason when
  the manager chose tracked km.
- The map: blue line = the tracked points (a break means no location came for over 10 minutes),
  grey band = the road route between the stops, numbered pins = the stops (red when outside the
  site's circle), the house = home.
- **Flags**: what the manager should look at, for example a check-in outside the pin with its
  reason, a day started or ended far from home, a day started on a holiday or weekly off, "End day
  not pressed: ended at the set time", an impossible jump, poor accuracy all day, a gap with no
  location, road km estimated.
- **Legs**: km and minutes per leg, "est." when estimated, and **Total by road**.
- **Stops**: each stop with times, minutes, the distance and reason when outside, and the selfie.
- **Km for the claim** (only for the person's manager, the director and the office admin, after the
  day ended): **Reason** (field), **Use road km** or **Use tracked km**. Tracked km needs a reason
  (for example a detour the stops do not show). Once the month's travel claim is approved by the
  manager, or the manager changed that day on the claim, the buttons are gone and a line says why:
  change the km on the claim instead.

**Rules**
- Nothing is recorded before **Start day**, after **End day**, on a day off, or without consent.
- The browser records only while this page is open. With the screen off or the browser closed the
  route can have gaps; the stops and road km still count.
- One day per date: once ended, a day cannot be started again that date.
- A site check-in needs the site and the selfie. Outside the site's radius (150 m by default) it
  needs a reason; the distance is shown to your manager. It is never rejected by itself.
- Check out of the last place before checking in at the next. **End day** checks you out of an open
  stop by itself.
- The claim uses road km from home through each stop and back home (from where the day started and
  to where it ended, when your home is not approved yet). When the map server is down, the road km are estimated (straight line
  x 1.3) and recalculated later.
- Who sees your route: you, your manager, the director and the office admin. Accounts see it only
  when they open it from your claim. Every view by someone else is logged.
- Location points are kept 90 days; the day's summary (stops, km) and approved claims 8 years.

**What happens next**
- Each ended day goes into your month's travel claim (Travel claims). On the 1st the claim is made
  ready and your manager gets it to approve.
- A site check-in counts as your attendance at that site for payroll.

**Hands off**
- Receives: your tracking profile, manager, rate per km and approved home from the office admin.
- Passes on: your days to your manager (Team map, Travel claims) and the attendance to payroll.

**When it goes wrong**
- "Location is blocked: allow location for this site in the browser": allow location in the
  browser's site settings, then try again.
- "Could not get your location; try again in the open": step outside or wait a few seconds.
- "This browser cannot give your location": use the phone's Chrome or Safari.
- "Give your consent first (My day > consent): nothing is recorded without it": press **I agree**.
- "Your day is already started" / "Today's day has already ended": reload the page; one day per
  date.
- "Your day is not started": press **Start day** first.
- "Start your day first": you tried to check in before **Start day**.
- "Check out of the last place first": check out, then check in at the new place.
- "Choose the site" / "Take the selfie (front camera) to check in at a site" / "Say where (a note)
  for another stop": fill in what is missing.
- "You are n m from <site>'s pin (the site is within n m): give the reason": write why in the box
  that appears. If the pin is wrong, tell the site engineer to correct the site's location.
- "You are not checked in anywhere": reload the page; you were already checked out.
- "Only the person, their manager, the director and the office admin see this route": the day is
  not yours to see.
- "The manager chooses the km of a day": you cannot change the km of your own day.
- "Give the reason for using tracked km (for example a detour the stops don't show)": fill in
  **Reason** before **Use tracked km**.
