---
page: /settings/checklists
title: Checklist templates
routes: /settings/checklists
mark: New checklist
---
The quality checklists used in site inspections. Each checklist is a list of checks, each a
pass/fail, a number, a text or a photo. Pick a checklist on a hold-point step in Settings › Stage
templates: that step is then certified only after a passed inspection with it. Every save is
written to the audit log.

**On the page**
- One card per checklist: its name, an **inactive** badge when switched off, and its checks in order, each with its type and ", required" when it must be answered.
- **New checklist**: opens the **New checklist** form. {perm: inspection.edit}
- **Edit** (on a card): opens **Edit checklist**. {perm: inspection.edit}

**The form (New checklist / Edit checklist)** {perm: inspection.edit}
- **Name**: the checklist's name. It must be unique. {perm: inspection.edit}
- **Check**: the text of one check. {perm: inspection.edit}
- **Check type**: **pass / fail**, **number**, **text** or **photo**. {perm: inspection.edit}
- **required**: the inspector must answer it. {perm: inspection.edit}
- **×**: removes that check. {perm: inspection.edit}
- **+ Item**: adds another check. {perm: inspection.edit}
- **Active**: untick it to stop the checklist being offered. {perm: inspection.edit}
- **Save**: saves and closes the form. {perm: inspection.edit}

**Rules**
- Only office roles with the inspection edit right for all sites change checklists. Site roles only use them.
- A checklist needs a name and at least one check.
- Inspections already done keep their answers when a checklist changes.

**What happens next**
- The site engineer or supervisor picks the checklist when recording an inspection. On a hold point with a checklist, the step is certified only after a passed inspection.

**Hands off**
- Receives: the quality checks from the director and planning.
- Passes on: the checklists the site teams inspect with.

**When it goes wrong**
- "A checklist named <name> exists": choose another name and press **Save** again. The message shows on the page behind the form, so the form seems to do nothing; closing the form loses what you typed.
- "Checklists are kept by the office (inspection.edit, all)": your role may not change checklists.
