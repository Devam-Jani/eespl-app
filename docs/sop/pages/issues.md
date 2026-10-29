---
page: /issues
title: Issue log
routes: /issues
---
The issue log lists what stops or risks the work on a site: material not arrived, short or damaged,
a product discontinued, a bill not accepted, over-billed or at the wrong rate, quality, leakage,
payment, site access or handover, a subcontractor dispute, other. You see the issues of your sites,
and any issue you raised or that is with you.

**On the page**
- Columns: **Issue** (code and title), **Site**, **Category** (red for leakage, yellow for material,
  blue for the rest), **Raised by** ("the system" when it was raised automatically), **With** (the
  person who has it), **Due** (red when it is past due and not resolved), **Status** (open, in
  progress, resolved, closed; with "shared with the client" and "linked to the guarantee" when they
  apply).
- Press a row to open it below: the details and every comment with who wrote it and when. Press it
  again to close it. A link from a notification opens the issue directly.
- **Comment** (field) and **Comment** (button): adds your comment to the issue. {perm: issues.edit}
- **Share with the client**: makes the issue a snag in the client portal (same title, details,
  person and due date). The client users of the site are notified. It is then shown as "shared with
  the client" and the button goes away. {perm: issues.edit}
- **Resolved…**: opens **Resolve <code>**. Type **What was done** (required) and press **Resolved**:
  the issue is marked resolved and "What was done: <text>" is added to its comments. The "Resolve
  it" task of the person who has it is closed. Not shown on a resolved or closed issue. {perm: issues.edit}
- **With** (on an open issue): pick who has the issue. **Due**: change the due date. **Add photos**:
  attach photos to the issue (the count shows on the button). {perm: issues.edit}
- **+ Raise an issue** (top right): opens **Raise an issue**. Pick the **Site \*** and the
  **Category \***, type **What is the issue \*** (at least 3 letters) and, if you like, **Details**,
  **Who has it**, **Due** and **Photos**. **Raise the issue** saves it (with the photos); **Cancel**
  closes without saving. {perm: issues.edit}

**Rules**
- A product marked discontinued raises an issue on every open methodology and site that uses it
  ("... discontinued: new method statement and client approval needed"). Saving a new version of
  the methodology without that product resolves the issue by itself, with a comment saying so.
- A leakage issue is linked to the signed guarantee that covers the area. If no signed guarantee
  covers it, the details say "Not under any of our signed guarantees on this site: check whether it
  is our work."
- A comment cannot be empty.
- A closed issue cannot be marked resolved again ("<code> is closed").
- Sharing an issue twice does nothing: it keeps the first snag.
- Only an issue of a site can be shared with the client.

**What happens next**
- When an issue is raised, the person it is with is told "It is yours" with the task "Resolve it",
  and the site engineer of the site is informed.
- An issue still open or in progress after its due date: the person who has it is reminded. Two days
  later it goes to the director.
- A shared issue is followed on the Snags page and by the client in the portal.

**Hands off**
- Receives: issues raised for a site (automatically when a product is discontinued, or by other
  parts of the app); the person it is with gets it in their notifications.
- Passes on: the client-facing point to the client as a portal snag; an overdue issue to the
  director.

**When it goes wrong**
- "Write the comment", or an error on the comment field: the comment box was empty. Type it, then
  press **Comment**.
- "Only a site's issue can be shared with the client": the issue is not tied to a site.
- "Issue not found": the issue is not on your sites and is not raised by you or with you.
- "Status is one of open, in_progress, resolved, closed": a wrong status was sent; refresh and try
  again.
