---
page: /settings/help
title: Help texts
routes: /settings/help
---
The short how-to behind the **?** button on each page: a title and 3 to 6 steps, for everyone or
for one role. Your text replaces the app's default; **Reset** brings the default back.

**On the page**
- One row per help text: **Page** (the menu name and the address under it), **For** (a role code, or "everyone"), **How-to** (the title, the number of steps, and **edited by <name>** when it was changed here).
- **Edit**: opens the editing form under the table for that row.
- **Reset**: on edited rows only. Deletes your text at once (no question asked); the default comes back.

**The editing form**
- The heading: the page and who it is for.
- **Title**: required.
- **Step 1** to **Step 6**: Steps 1 to 3 are required; 4 to 6 are optional. Empty steps are dropped.
- **Save**: saves the text. Everyone opening that page (or everyone of that role) sees it in the **?** at once.
- **Cancel**: closes the form without saving.

**Rules**
- Only pages that already have a help text are listed. A help text for a new page or a new role cannot be added here.
- A person sees the help text for their own role first. When there is none, they see the one for everyone. With several roles, the first role that has one is used.
- Keep each step to one action, in plain words, with the button names as they are on screen.
- Every save and reset is in the **Audit log** (help.edit, help.reset).

**Hands off**
- Receives: a question that keeps coming back from people using a page.
- Passes on: nothing. The new text shows by itself.

**When it goes wrong**
- "Give 3 to 6 steps": fill at least three steps.
- "Missing permission: help.edit": your role cannot change help texts.
