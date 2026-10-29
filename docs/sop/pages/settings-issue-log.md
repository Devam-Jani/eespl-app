---
page: /settings/issue-log
title: Issue log
routes: /settings/issue-log, /settings/issue-log/:id
mark: ⤓ Export Excel
---
The log book of everything that went wrong in the app: errors, wrong entries the helper guided,
problems users reported and the nightly check's findings. The same problem seen again is counted
on the same line. Each line is followed from **New** to **Fixed** and released.

**On the page**
- The week at the top: **New this week**, **Times something went wrong**, **Open bugs**, **Fixed / released this week**.
- **⤓ Export Excel**: downloads the whole log as an Excel file.
- **Status** (filter): **Any**, **New**, **User mistake, guided**, **Bug**, **Being fixed**, **Fixed**, **Will not fix**.
- **Kind** (filter): **Any**, **Error**, **Wrong entry**, **User's report**, **Nightly check**.
- **Search** (field): finds words in the problem's title, the page or the error text.
- The table: **#**, **Problem** (with its kind, the HTTP code and a "pull request" link when set), **Page**, **Roles**, **Times**, **First seen**, **Last seen**, **Found by**, **Status**.
- The problem's title: opens the issue.

**Inside an issue**
- **← Issue log**: back to the list.
- The line under the title: kind, page, how many times, first and last seen, roles, found by.
- **What happened**: the error text, **Stack (last lines)** to open, and **The helper's answers** when the user asked the helper.
- **Status**: the status of the issue.
- **Cause**, **Fix**, **Pull request link**, **Commit**, **Fixed at**: shown when the status is **Bug**, **Being fixed** or **Fixed**.
- "Released: …": the date the fix went live, or "not yet (marked on the deploy that carries the commit)". **open the pull request** opens the link.
- **Save**: saves the status and fix. "Saved." shows. {perm: issuelog.edit}
- **Each time (n)**: every time it happened: **When**, **Role**, **Page and action**, **Request**, **Browser**, **The user's words**, and **What they typed (sent with consent)** when the user agreed to send it.

**Rules**
- Only the director, the office admin and the super admin see the log. Changing it needs the issue log edit right.
- Setting **Fixed** without a **Fixed at** date fills in now.
- **Released** is set by the deploy that carries the commit, not by hand.
- The person who reported a problem sees its status and fix in My reports.

**What happens next**
- Every week the director, the office admin and the super admin get a summary of the log book in their bell.

**Hands off**
- Receives: reports from every user (Report a problem), errors caught by the helper, and the nightly check.
- Passes on: bugs to whoever fixes the app; the status back to the reporting user in My reports.

**When it goes wrong**
- A **Pull request link** that is not a GitHub pull request address, or a **Commit** that is not 7 to 40 letters and digits, is refused next to the field.
- "Issue not found": the issue number is wrong. Go back to the list.
