---
role: index
title: Index - users and logins (super admin)
width: 1600
---
## The SOPs

There is one SOP per role. A person reads their own role's SOP in the app (**How to**, at the top of every page, or **How to (my SOP)** in their menu). The super admin and the director can read all of them. The printed copies are "EESPL SOP - <Role>.pdf" and ".docx".

| SOP | For |
|---|---|
| Super admin | users, roles, security and backups |
| Director | the whole company, approvals above the limits |
| Office admin | settings, masters, help texts, day-to-day support |
| Planning | sites, stages, estimates, material approvals |
| Sales | leads, quotations, tenders, client follow-up |
| Estimator | BOQs and rates, the rate library |
| Site engineer | the site's reports, material, snags (phone) |
| Site supervisor | the day on site: report, attendance, deliveries (phone) |
| Site receiver | the applicator's person who counts deliveries (phone) |
| Billing | measurements, work orders, RA bills |
| Accounts | receipts, vendor bills, payroll, Tally |
| Store and purchase | indents, POs, GRNs, stock |
| Client | the client portal of their own sites |

## Giving a new person a login

The steps below use the training company first if you want to practise: it is reset every night, and nothing there reaches the real company.

1. **Administration > Users > Add user.** Fill in **Full name**, **Email** (their sign-in name), **Phone** and **Job title**.
2. **Password (at least 10 characters)**: type a long random one. Nobody needs to know it, because the person chooses their own with the link in step 5.
3. **Roles**: tick the person's role. One person may hold two or more roles (for example Billing and Accounts). They then get every page and button of each role, and read the SOP of each. There is no limit on users, in total or per role.
4. **Save**. The page says "<name> added."
5. On the person's row, press **Set-password link**. The link is copied, and is shown in the green notice: "One-time link for <name> (copied; works once, 7 days): <link>".
6. **Send the link yourself.** The app never e-mails it, and e-mail is off on the test server. Paste it into a WhatsApp message to the person, with one line: "Open this link on your phone, choose your password (at least 10 characters), then sign in." The link works once and lasts 7 days. If it expires or gets lost, press **Set-password link** again: the new link stops the old one.
7. **Sites.** Site engineers, site supervisors, site receivers and sales see a site only when they are on its team. Open **Sites** > the site > **Overview** > **Team on site** > **Add person**. Pick the **Member** and the **Role on site**, then press **Save team**.
8. **Two-step sign-in.** If it is required for the person's role (Administration > **Security**), they set it up at their first sign-in with an authenticator app.
9. Point them to their SOP: **How to** at the top of every page.

For many people at once, use **Administration > User import** (an Excel file with the roles and sites). Imported users show "Active" although they have no password yet (see the bugs list). Send each person a **Set-password link**.

## When someone is locked out or forgot their password

- There is no "forgot password" on the login page: the person asks you.
- **Set-password link** (best): send it as above. Only the person learns the new password.
- **Reset password**: type a new one for them. They are signed out on every device.
- **Unlock**: 5 wrong passwords lock the sign-in for 15 minutes. The third lock in a row waits for you. While locked, the login page says only "Invalid email or password".
- **Reset two-step**: for a lost or changed phone.

## When someone leaves

1. **Users** > their row > **Deactivate**. Every session ends at once, and the password stops working.
2. Take them off each site's **Team on site**, and hand their open work to someone else. Deactivating does neither.
3. Do not send a deactivated person a set-password link. Using it makes the account active again (see the bugs list).
4. Users cannot be deleted. Their name stays on what they did, and the audit log keeps it.

## The pages

@page /admin/users
@page /admin/user-import
@page /admin/roles
@page /settings/security
@page /settings/roles-report
@page /settings/team
@page /admin/audit

{{first-login}}

## Quick card

1. New person: **Add user** → role(s) → **Save** → **Set-password link** → WhatsApp it → add to the site teams.
2. Forgot password: **Set-password link** again.
3. Locked: **Unlock**.
4. Lost phone: **Reset two-step**.
5. Leaves: **Deactivate** the same day, then take them off the site teams.
