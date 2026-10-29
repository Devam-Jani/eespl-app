---
page: /tc-library
title: T&C library
routes: /tc-library
mark: Add clause
---
The **T&C library** holds the terms and conditions clauses we put in quotations, grouped by category, and the templates (ordered sets of clauses) a quotation starts from. Other wordings of the same clause are kept as variants, so a client's BOQ can be matched to our clause.

**On the page**
- **Clauses** and **Templates** (tabs): switch between the clause list and the templates.
- **Clauses that give free-issue materials away (n)** (card, only when there are any): clauses saying we supply free what the client supplies free of cost (cement, sand, water and the like). Each shows "Says:" and "Should read:". {perm: estimate.view}

**Clauses tab**
- **Filter clauses** (box): shows only clauses (or variants) containing the words.
- **Needs review (n)** (button): shows only the clauses marked for review. Press again to show all.
- **Show hidden (n)** (tick box): also lists the hidden clauses, greyed.
- **⤓ Export Excel**: downloads the clauses, with the hidden ones when **Show hidden** is ticked and only those to review when **Needs review** is on.
- **Add clause**: opens the **Add clause** form. {perm: library.edit}
- Each clause shows its text, "used in n BOQs", **default** when it is included by default, **n variants** (click to list the other wordings), the hidden reason, and **Needs review: <note>** in orange.
- **↑** and **↓**: move an active clause up or down in its category. {perm: library.edit}
- **Edit**: opens the clause in the form. {perm: library.edit}
- **⋯** (more actions): **Hide…**, or **Unhide** on a hidden clause; **Merge into…**; **Mark reviewed** on a clause that needs review. {perm: library.edit}
- **Unmerge** (in the variant list): makes the variant a clause of its own again. {perm: library.edit}

**The clause form (Add clause / Edit clause)** {perm: library.edit}
- A yellow note "<review note>. Correct the text and save to clear this." when the clause needs review. {perm: library.edit}
- **Text** (required), **Category** (required; type or pick an existing one), **Include by default**. {perm: library.edit}
- **Save** saves. Changing the text of a clause that needs review clears the review mark. **Cancel** closes. {perm: library.edit}
- **Delete** (edit only): asks "Delete this clause? It is also removed from every template." {perm: library.edit}

**Hide clause window** {perm: library.edit}
- **Reason**: **Not a clause**, **Client checklist answer**, **Project-specific** or **Hidden by hand**. **Hide** hides it; **Cancel** closes. Hidden clauses are also taken out of every template. {perm: library.edit}

**Merge into… window** {perm: library.edit}
- **Search clauses** (box), then click the clause to keep (the master) and confirm "Merge into this clause?". This wording is kept as a variant, its usage count is added to the master, and templates that held it get the master instead. You can unmerge later. {perm: library.edit}

**Templates tab**
- **Templates** (list): each template with its number of clauses and **default** on the default one. Click a template to open it. The first one opens by itself.
- **New**: asks "Name of the new template" and creates an empty template. {perm: library.edit}
- **Rename**: asks "Rename template" with the current name. {perm: library.edit}
- **Make default**: makes this template the default one (the previous default stops being default). {perm: library.edit}
- **Delete**: asks "Delete the template "<name>"? The clauses themselves are kept." {perm: library.edit}
- The template's clauses in order, with their category. **↑** and **↓** move a clause; **×** takes it out of the template. {perm: library.edit}
- **Add a clause** (list, "Add a clause…"), then **Add**: adds an active clause at the end. {perm: library.edit}

**Rules**
- A clause can appear only once in a template. Hidden and merged clauses cannot be in a template.
- A clause with merged variants cannot be deleted until they are unmerged.
- Every change is written to the audit log, and a clause changed by hand is marked as decided by a person.

**What happens next**
- A new tender copies the clauses of the template chosen for it, or of the default template when none is chosen. Later changes to the library do not change tenders already made.

**Hands off**
- Receives: clauses read from past BOQs and quotations.
- Passes on: templates and clauses to the estimator and sales for quotations.

**When it goes wrong**
- "No clauses.": nothing matches the filter, or **Needs review** is on with nothing to review.
- "This clause has merged variants; unmerge them first": open the variants and press **Unmerge** on each.
- "A clause cannot be merged into itself", "This clause is already merged into another clause", "The target clause is itself merged; merge into its master": choose another clause.
- "A template with this name already exists": choose another name.
- "A clause can appear only once in a template" or "Hidden or merged clauses cannot be in a template: [...]": the clause is already in the template, or it was hidden or merged meanwhile. Reload.
- The free-issue card shows no button to correct the text. Correct the clause by hand with **Edit**, using the "Should read:" text. {perm: library.edit}
