---
page: /admin/users
title: Users
routes: /admin/users
mark: Add user
---
Everyone who can sign in to the app, staff and client contacts alike: name, email (the sign-in
name), phone, roles, status and last sign-in. Here you add a person, give them their roles, hand
them a one-time link to set their password, reset or unlock a sign-in and deactivate someone who
leaves. Every change is written to the audit log.

**On the page**
- **Search name or email**: narrows the list as you type.
- **Export Excel**: downloads the list (name, email, phone, job title, roles, active, has password, last login).
- **Add user**: opens the **Add user** form.
- The columns: **Name**, **Email** (the job title under it), **Phone**, **Roles** (one chip per role), **Status**, **Last login** (India time).
- **Status** is one of: **Active**; **Inactive** (deactivated); **Not set up** (inactive and no password yet); **Locked 15 min** (5 wrong passwords in a row); **Locked: unlock** (locked for the third time in a row: waits for you).
- The buttons on each row: **Edit**, **Reset password**, **Set-password link**, **Unlock** (only on a locked row), **Reset two-step** (only when the person uses two-step sign-in), **Deactivate** or **Activate** (never on your own row).

**Add user (the form)**
- **Full name**: required. Printed on letters, bills and every record the person makes.
- **Email**: required, and must be new. It is the person's sign-in name and is stored in small letters.
- **Phone**: optional.
- **Job title (printed on letters and bills, e.g. Assistant Manager Billing)**: optional, up to 100 characters.
- **Password (at least 10 characters)**: required. The person can sign in with it at once. Use a long random one if you will send a set-password link (see below).
- **Roles**: tick one role or several. A greyed role shows "This role has permissions you do not hold" when you point at it: you cannot give it.
- **Save**: creates the user, active at once, with the roles ticked. The page says "<name> added."
- **Cancel**: closes without saving.

**Several roles, and the limits**
- One person may hold several roles. They get every permission of every role; where two roles give the same permission, the wider reach wins (all, then assigned, then own).
- Their menu shows the pages of all their roles together, and every button any of their roles allows.
- A role change counts at once, on the person's next click: no new sign-in is needed.
- There is no limit on the number of users, in total or per role. The app has no licence or seat count.
- A client contact (the client role) can never also hold a role with admin rights, tender margins or finance editing. Saving such a mix gives "Client users cannot have: ...". A person with the client role and a staff role uses the staff app, not the portal.
- Client contacts are normally invited from the site's **Portal** tab, not added here. {perm: portal.manage}

**Edit (the form)**
- The same fields as **Add user**, without the password. Change the name, email, phone, job title or the roles, then **Save**. The page says "<name> updated."
- **Kylas user id (owner of the Kylas leads this person enters)**: only numbers. Links the person to their user in Kylas so their leads come in under their name. {perm: admin.settings}
- Changing the email changes the person's sign-in name. Tell them.

**Giving a person their sites**
- Roles say what a person may do; site roles (site engineer, site supervisor, site receiver, sales) also need the person on the site's team to see that site.
- The team is set on the site: **Sites** > the site > **Overview** > **Team on site** > **Add person**, choose the **Member** and the **Role on site**, then **Save team**. {perm: site.edit}
- **User import** sets the sites from the Excel file for new people.

**The first password: Set-password link**
- **Set-password link**: makes a one-time link for the person to choose their own password. The page shows "One-time link for <name> (copied; works once, 7 days): <link>" and copies it to the clipboard.
- The app never emails this link, even when email is switched on. Copy it from the green notice and send it yourself (WhatsApp, SMS or email).
- The link works once and for 7 days. Making a new link stops the earlier unused one.
- When the person sets a password with the link, the account is made active and every earlier password and session ends. Then they sign in on the login page.
- If the browser could not copy (the app opened on a plain http address), the notice still says "copied": select the link in the notice and copy it by hand.
- Training (DEMO) users have no links: "User not found".

**Reset password**
- **Reset password**: opens **Reset password: <name>**. Type **New password (at least 10 characters)** and **Repeat password**, then press **Reset password**.
- The new password must not be a common one, nor contain the person's name or email, nor be one character repeated or a plain sequence.
- The person is signed out on every device at once. The page says "Password reset for <name>. They have been signed out everywhere." Tell them the new password, or send a **Set-password link** instead so only they know it.
- A reset also lifts a lock from wrong passwords.
- There is no "forgot password" on the login page. A person who forgot theirs asks you for a reset or a new link.

**Unlock**
- 5 wrong passwords in a row lock the sign-in for 15 minutes. The third lock in a row stays until you press **Unlock**.
- **Unlock**: clears the lock at once. The page says "<name> unlocked". The person still uses their own password.
- While locked, the login page says only "Invalid email or password", even for the right password. Check this list when someone says their password stopped working.

**Reset two-step**
- **Reset two-step**: for a lost or changed phone. Asks "Turn two-step sign-in off for <name> (a lost phone)?". Then the page says "Two-step sign-in reset for <name>".
- If two-step sign-in is required for the person's role (Administration > **Security**), they set it up again at their next sign-in.

**Deactivate (someone leaves)**
- **Deactivate**: asks "Deactivate <name>? They will be signed out and unable to log in." Then the page says "<name> deactivated."
- Every session of theirs ends at once: their next click on any device takes them to the login page. Their password no longer works ("Invalid email or password").
- Users cannot be deleted. Their name stays on every report, bill and record they made, and the audit log keeps their history.
- Deactivating does not take them off site teams or hand over their open work. Remove them from **Team on site** on each site and pass their open items to someone else.
- Do not send a set-password link to a deactivated person: using the link makes the account active again.
- **Activate**: brings a deactivated user back. The page says "<name> reactivated." A user with no email or no password cannot be activated: send a **Set-password link** instead (using it activates them).

**Rules**
- Nobody can give more than they have. You can only tick roles whose permissions you hold yourself, at the same or a wider reach.
- You can only edit, reset, deactivate or reactivate someone who has no permission you lack.
- With the roles as set today, the office admin can give only the Estimator, Site receiver and Office admin roles, and can edit or reset only people with those roles. Everyone else is added and managed by the super admin, unless the office admin role is given more permissions in Roles & permissions.
- You cannot deactivate yourself.
- An email can belong to one user only.

**What happens next**
- A new person: send the link (or the password). They sign in, and if their role requires it, set up two-step sign-in at that first sign-in.
- Every add, edit, role change, reset, link, unlock and deactivation is in the **Audit log** with who did it.

**Hands off**
- Receives: the joiner's name, email, phone and job from the director or the department head; a "locked out" or "lost phone" call from the person.
- Passes on: the one-time link to the person; the site team change to whoever runs the site (Sites > Team on site).

**When it goes wrong**
- "A user with this email already exists": that email is in use, maybe by a deactivated user. Search for it and reactivate or edit that user.
- "You cannot assign roles that grant permissions you do not hold: ...": a ticked role gives something you lack. Ask the super admin to add the person.
- "You cannot manage a user who has permissions you do not hold": the person has a role with more than you. Ask the super admin.
- "Client users cannot have: ...": the client role is mixed with a role that has admin, margin or finance rights. Untick one.
- "Set an email and a password before activating this user": the user has no password. Press **Set-password link** and send it; using it activates them.
- "You cannot deactivate yourself": ask another admin.
- "The password needs at least 10 characters", "That password is too common: choose another", "The password must not contain your name", "The password must not contain your email", "The password repeats the same characters: choose another", "The password is a plain sequence: choose another": choose another password.
- "Passwords do not match": the two boxes of **Reset password** differ. Type them again.
- "Missing permission: admin.settings (Kylas user id)": only the super admin sets the Kylas user id.
