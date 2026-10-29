---
page: /settings/categories
title: Categories
routes: /settings/categories
mark: Add category
---
The two lists of categories that fill the dropdowns across the app. **Work** categories say where
on site the work is (used on tasks, work orders and issues). **Material** categories say what
kind of product it is (used on products). Every change is written to the audit log.

**On the page**
- **Work** / **Material** (tabs): switch between the two lists.
- The table: **Name**, **Parent**, **Order**, **Products** (Material tab only: how many products use it) and **Status** (**Active** or **Inactive**). Inactive rows are greyed.
- **⤓ Export Excel**: downloads the list of the open tab as an Excel file.
- **Add category**: opens **Add work category** or **Add material category**.
- **Edit** (on a row): opens **Edit <name>**.

**The form**
- **Name**: up to 100 characters. It must be unique within its kind (capitals do not count).
- **Parent (optional)**: another category of the same kind, to group it under.
- **Order**: a number; lower numbers come first in the lists.
- **Active**: untick it to hide the category from new choices while keeping old records.
- **Save**: saves and closes the form.
- **Cancel**: closes without saving.
- **Delete**: shown when editing. Asks "Delete "<name>"?" and removes it.

**Rules**
- A category used by products cannot be deleted. Untick **Active** instead.
- A category cannot be its own parent.

**What happens next**
- The new or renamed category shows at once in the product, task, work order and issue forms.

**Hands off**
- Receives: requests for a new category from estimators, planning or stores.
- Passes on: the lists the other roles pick from.

**When it goes wrong**
- "A category with this name already exists": pick another name, or edit the one that exists.
- "<n> products use this category; deactivate it instead": untick **Active** and save.
- "Parent must be another category of the same kind": choose a different parent, or none.
