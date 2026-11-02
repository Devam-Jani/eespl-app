---
page: /settings/stage-templates
title: Stage templates
routes: /settings/stage-templates
mark: New template
---
The steps of each kind of work (for example primer, membrane, protection screed), with the weight
of each step in the progress, whether it needs a photo or an inspection, the hold points and the
typical days. Sites get their tasks from these templates. Every save is written to the audit log.

**On the page**
- The list on the left: each template with its number of steps, total days, work category and "inactive" when switched off. Click one to open it.
- **New template**: opens an empty template with one step at 100 %. {perm: site.edit, planning.edit}
- **Name**: the template's name. It must be unique.
- **Keywords (suggest this template for BOQ lines with these words)**: words that make the app suggest this template for a BOQ line.
- Under the name: the template's **Work category** and **system** (read only).
- The steps table: **#**, **Step**, **Weight %**, **Photo**, **Inspection**, **Hold point**, **Hold-point checklist**, **Days**.
- **Photo**: the step needs a photo to be marked done.
- **Inspection**: the step needs an inspection.
- **Hold point**: the next work waits until this step is certified.
- **Hold-point checklist**: shown on a hold point. Pick a checklist (from Checklist templates) and the step is certified only after a passed inspection with it; or **— none —**.
- **Days**: the typical days for the step, 1 or more.
- **↑** / **↓**: move the step up or down. {perm: site.edit, planning.edit}
- **×**: remove the step. {perm: site.edit, planning.edit}
- "Weights add up to <n>% ✓" or "(must be 100)" in red under the table.
- **Add step**: adds an empty step at the end. {perm: site.edit, planning.edit}
- **Active**: untick it to stop the template being offered. {perm: site.edit, planning.edit}
- **Save template**: saves; "Template saved." shows. It stays greyed until the weights add up to 100 and there is a name. {perm: site.edit, planning.edit}
- Without the site edit right or the planning edit right the fields are greyed and there are no buttons.

**Rules**
- The step weights must add up to exactly 100.
- A step that already has tasks on a site cannot be removed. Set its weight to 0 instead. {perm: site.edit, planning.edit}
- A changed weight of an existing step applies on every site using it at once.
- A new step reaches a site only when the site's tasks are generated again.

**What happens next**
- Planning and the site teams see the steps on each site's tasks. Hold points block the next work until certified.

**Hands off**
- Receives: the method of each kind of work from planning and the director.
- Passes on: the task steps the site engineer and supervisor work through.

**When it goes wrong**
- "Step weights must add up to 100 (they add up to <n>)": fix the weights so they total 100.
- "A template named '<name>' exists": choose another name.
- "'<step>' has tasks on sites; keep it (set its weight to 0) instead of removing it": put the step back and set its weight to 0.
- "Template not found": someone removed it; reload the page.
