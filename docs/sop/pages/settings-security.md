---
page: /settings/security
title: Security
routes: /settings/security
---
The sign-in rules for everyone: which roles must use two-step sign-in, and how long a session
lasts unused. Each change saves itself and is written to the audit log.

**On the page**
- **Two-step sign-in**:
  - **Required for these roles (they set it up at their next sign-in)**: the switch. Ticking or unticking it saves at once ("Saved").
  - One tick box per role (the client role is not listed). Ticked roles are the ones the switch applies to. Director, Office admin and Accounts are ticked from the start, but the switch starts off. Each tick saves at once.
  - "The office admin resets a person's two-step sign-in in Users when a phone is lost."
- **Sessions and passwords**:
  - **End a session after this many hours unused on a phone**: 1 to 72; 12 to start with. Saved when you leave the box.
  - **…on a desktop**: 1 to 72; 8 to start with. Saved when you leave the box.
  - The fixed rules, for reading: passwords at least 10 characters and not a common one; 5 wrong passwords lock the sign-in for 15 minutes; the 3rd lock in a row waits for the office admin (Users > **Unlock**); a password change ends every session.

**Rules**
- With the switch on, a person holding a ticked role who has not set up two-step sign-in is asked to set it up right after their password, at the next sign-in. They cannot get in without it.
- Turning the switch off or unticking a role does not turn two-step off for people who set it up. They can turn it off themselves in **My account**.
- While their role requires it, people cannot turn two-step off in **My account**.
- "Unused" means no use of the app. A session past the limit ends at the next refresh: the person signs in again.

**What happens next**
- Tell the people of a newly ticked role to keep their phone at hand for their next sign-in, with Google or Microsoft Authenticator installed.
- A lost phone: the office admin presses **Reset two-step** on the person in **Users**. {perm: admin.users}

**Hands off**
- Receives: the director's decision on who must use two-step sign-in.
- Passes on: the news to the people of those roles.

**When it goes wrong**
- A number outside 1 to 72 is refused and not saved. Type a number in that range.
- "Missing permission: one of admin.users, system.ops": your role cannot change the security settings.
