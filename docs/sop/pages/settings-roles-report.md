---
page: /settings/roles-report
title: Who sees what
routes: /settings/roles-report
mark: PDF for sign-off
---
Each role's pages and actions in plain words, and what it never sees, worked out from the real
permissions in Roles & permissions. Print the PDF for the director to sign before go-live and
after every change of roles.

**On the page**
- **PDF for sign-off**: downloads roles-report.pdf, the same report on paper.
- One row per role: **Role** (with the number of permissions), **Menu** (the menu groups it sees; the client role shows "the client portal only"), **Never sees** (the sensitive things it can never open, such as costs or margins).
- Click a row to open it:
  - **Pages**: each menu group with the pages the role opens.
  - **May do**: each action the role may take, with its reach in brackets (every record, the sites it is assigned to, or its own records).
- Click the row again to close it.

**Rules**
- The report is read-only. To change what a role sees, change it in **Roles & permissions**, then look here again. {perm: admin.roles}
- A person with several roles sees what all their roles see together.
- Extra rights given to one person by the director (outside their roles) are not in this report.

**Hands off**
- Receives: a change of roles.
- Passes on: the signed PDF to the director's file.

**When it goes wrong**
- "Missing permission: system.ops": your role cannot open this report.
