---
page: /notifications
title: Notifications
routes: /notifications
mark: My email choices
---
Every notification sent to you, newest first: the to-dos from the process rules, information
messages and alerts. The bell at the top of every page shows the latest ones; this page has them
all with filters. For roles without a dashboard, the **Alerts** item in the side menu opens this
page.

**On the page**
- **My email choices**: opens My notifications, where you choose which steps also come by email.
- **All** (tab): every notification you got (the latest 100).
- **Mine to act (n)** (tab): the open to-dos only. n is how many are still open.
- **Information** (tab): messages that need no action.
- **Escalated (n)** (tab): to-dos that went past their time and were escalated. n counts the open
  ones; the tab shows no number when there are none.
- Each row: the title in bold, the detail lines, then a small line with when it came,
  "· escalated", a note, "· email <state>" when it was also emailed, and either "· waiting n h" /
  "n d" or "· done <when> by <who>: <reason>".
- Unread rows are highlighted. Escalated rows are red; open to-dos are orange.
- Press a row: it is marked read and its page opens.
- The action button on an open to-do (for example **Approve**, **Review**; **Open** when the rule
  names none): marks it read and opens its page, where you do the step.
- **Done**: closes the to-do by hand. Type the **Reason** (at least 3 characters, "Why was
  "<action>" not done in the app?") and press **Close it**; **Cancel** keeps it open.
- A row with no action shows the badge **info**; a closed to-do shows **done**.
- "Nothing here." shows when the tab has nothing.

**The bell (top of every page)**
- The red number is your unread count (99+ above 99). It refreshes every minute.
- Press the bell to see the latest; press one to open it (it is marked read).
- **Mark all read**: marks every notification read. Nothing is deleted.
- **See all, with filters →**: opens this page.

**Rules**
- A to-do closes by itself when the step is done in the app. **Done** is only for a step done
  outside the app; the reason shows on the site's process timeline.
- **Done** closes the to-do for everyone who got it for the same item, and stops its escalations.
- Nothing is ever deleted from the list. Read and closed rows stay as a record.
- Escalations always come by email as well, whatever you chose in My notifications (when the
  company has email switched on).

**What happens next**
- Open each to-do and do its step; it moves from **Mine to act** to done by itself.
- If you leave a to-do open past the time in Settings > Process rules, it escalates to the roles
  named there and shows under **Escalated**.

**Hands off**
- Receives: notifications from every step the other roles take on your sites, jobs and claims, and
  the hourly alerts.
- Passes on: your step on the linked page notifies the next role.

**When it goes wrong**
- "Say briefly why '<action>' was not done in the app": write a reason of at least 3 characters.
- "Nothing to close": it was already closed. Reload the page.
- "Notification not found": it is not yours, or it is gone. Reload the page.
- You press a row and nothing seems to happen: the notification has no page to open. It is marked
  read on the server; reload the page to see it as read.
