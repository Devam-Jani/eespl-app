---
page: /admin/audit
title: Audit log
routes: /admin/audit
mark: Apply
---
The record of who did what and when: every sign-in (and failed sign-in), export, permission
change, deletion, view of someone's route, and the changes to users, roles and records. Nobody
can edit or delete an entry. Newest first, 50 to a page.

**On the page**
- **Kind**: **Everything**, **Sign-ins**, **Exports and downloads**, **Permission changes** (roles, user roles, grants, client roles, unlocks, security settings), **Deletions** (anything deleted, and deactivated users), **Views of someone's route**.
- **User (email)**: part of the email of the person who acted, e.g. "admin@".
- **Entity**: **Any**, **User**, **Role**.
- **Action**: **Any**, **auth.\* (logins)**, **auth.login_failed**, **auth.lockout**, **user.\***, **role.\***.
- **From**, **To**: the dates, both included.
- **Apply**: shows the entries matching the filters, from the first page.
- **Clear**: empties the filters and shows everything.
- **Export Excel**: downloads the entries matching the filters that are applied (up to 20,000 rows), with the before and after of each.
- The columns: **When** (India time), **User** (— for the system or an unknown email), **Action** (a code such as user.create or auth.login_failed), **Entity** (and the start of its id), **IP**.
- **Details**: on entries that keep a before or after. Opens **Before** and **After** side by side. **Hide** closes them.
- **Previous**, **Next**: the pages. "1–50 of n" says where you are.

**Rules**
- The filters only count after **Apply**. **Export Excel** uses the applied filters, not what is typed but not applied.
- **From** and **To** count whole days in UTC, while **When** is shown in India time. An entry made before 05:30 in the morning India time belongs to the day before.
- A failed sign-in keeps the email that was typed and the reason (unknown email, wrong password, locked, no password, inactive), though the person only ever saw "Invalid email or password".

**What happens next**
- Nothing changes from this page. Use it to answer "who changed this?" and to check sign-ins after a lock or a lost phone.

**Hands off**
- Receives: a question from the director about a change, a lock or an export.
- Passes on: the export to the director when asked.

**When it goes wrong**
- "No entries match these filters.": widen the dates or clear the **User (email)** box.
- "Missing permission: audit.view": your role cannot open the audit log.
