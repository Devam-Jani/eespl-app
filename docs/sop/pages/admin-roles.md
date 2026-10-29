---
page: /admin/roles
title: Roles & permissions
routes: /admin/roles
mark: New role
---
The grid of every role (a column each) against every permission (a row each, grouped by module).
Each cell says how far the role reaches for that permission. A person's rights are the sum of
their roles. Changes count at once for everyone holding the role, on their next click.

**On the page**
- **New role**: opens the **New role** form.
- The line under the title: **all** = every record, **assigned** = only sites/tenders the user is assigned to, **own** = only records the user created. A user with several roles gets the widest scope.
- Each column head: the role's name, its code and how many users hold it. A lock marks a system role (it cannot be deleted). Point at the head to read the role's description.
- Each row: the permission code and what it allows.
- Each cell: **—** (not given), **all**, **assigned** or **own**. Changing a cell changes only your draft of that column.
- Under each column:
  - **Save**: saves that column's changes. The page says "Permissions for <role> saved." Greyed until something changed.
  - **Undo**: puts the column back as it was saved. Shown when something changed.
  - **Delete**: on roles that are not system roles. Asks "Delete the role "<role>"?" and, when people hold it, "It is assigned to n user(s), who will lose it." Then "Role <role> deleted."
  - **Always all**: under Super admin. Its column cannot be changed.
  - **Can be added to, never reduced**: under Director. You can widen or add, never lower or remove.

**New role (the form)**
- **Name**: required. The code is filled in from it as you type.
- **Code (lowercase letters, digits and _)**: starts with a letter, 2 to 50 characters. Cannot be changed later.
- **Description**: optional; shown when pointing at the column head and on the Users form.
- **Create role**: makes the role with no permissions. The page says "Role <name> created. Set its permissions in the grid, then save."
- **Cancel**: closes.

**Rules**
- You can only give permissions you hold yourself, at the same or a wider reach. Lowering or removing is always allowed (except on Director).
- The Super admin role always has every permission.
- The Director role can be given more, never less.
- The client role can never have admin permissions, **tender.margin** or **finance.edit**. Nor can a role held by any client contact.
- System roles cannot be deleted. Deleting another role takes it from everyone who held it, at once.
- A new role gives nobody anything until you tick it for people in **Users**.
- There is no limit on the number of roles or on the users per role.
- Every change is in the **Audit log** (kind **Permission changes**), with the before and after.

**What happens next**
- People holding the role see the new pages and buttons on their next click, or lose them.
- Administration > **Who sees what (roles)** shows the result in plain words for the director's sign-off. {perm: system.ops}

**Hands off**
- Receives: the director's decision on what a job may see or do.
- Passes on: the updated "Who sees what" report to the director for sign-off.

**When it goes wrong**
- "You cannot grant permissions you do not hold: ...": you tried to give something you do not have. Ask the super admin.
- "The <role> role cannot lose permissions: ...": the Director role cannot be reduced. Undo those cells.
- "This role always has every permission and cannot be edited": the Super admin column.
- "The client role cannot have: ..." / "This role is held by client users, who cannot have: ...": remove those permissions, or take the role away from the client contacts first.
- "A role with this code already exists": choose another code.
- "System roles cannot be deleted": only roles you made can be deleted.
