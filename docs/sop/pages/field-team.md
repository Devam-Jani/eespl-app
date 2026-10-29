---
page: /field/team
title: Team map
routes: /field/team
---
The team map shows today's latest location of each person you manage, the time of that point, and
who has not started the day. The director and office admin see everyone who is tracked. Every time
the page is opened it is logged.

**On the page**
- The map: one pin per person who has a location today, with their initials. Press a pin to see the
  name, "last at" time and, when they are checked in, the place ("at ...").
- **Person**: the people who started the day. Press a name to open that person's day (route, stops,
  flags).
- **Last point**: the time of their latest location (or of the day's start).
- **Now**: "day ended", "at <place>" when checked in at a site or client, or "on the way". In red,
  "n flag(s)" when the day has flags (for example, a check-in outside a site's radius).
- **Not started today (n)**: the people who have not started their day yet.
- The page refreshes by itself every two minutes.

**Rules**
- You see only the people whose tracking profile names you as their manager.
- The director and office admin see everyone whose tracking is on. {perm: field.team}
- A location is recorded only while the person's day is on, from Start day to End day on My day
  (check-in). The pin is their latest point of the last 20 hours.

**What happens next**
- Use it to see who is where before calling or sending someone to a site. A person not started by the
  usual time can be followed up by phone.

**Hands off**
- Receives: the locations recorded by each person's My day (check-in) page.
- Passes on: nothing; it is for looking only.

**When it goes wrong**
- The map is empty and the lists are empty: no one has you as their manager in the tracking
  profiles. Ask the office admin to set the manager.
- A person is missing from the map but listed under **Person**: their phone has not sent a location
  yet today.
- "Missing permission: field.track": your role does not open the team map.
