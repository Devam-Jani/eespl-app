---
page: /indents
title: Material indents
routes: /indents
mark: New indent
---
The list of material indents: a site's request for material. Each row shows the code, the site,
the items, the date it is needed by, the status and who raised it. An indent is raised, approved,
then turned into an RFQ or a purchase order (PO). You see the indents of your own sites, or all of
them if your role covers every site.

**On the page**
- **Status** (filter): **All statuses**, or one of draft, submitted, approved, partly ordered,
  ordered, closed, rejected, cancelled.
- **Site** (filter): **All sites**, or one site.
- A row: opens the indent (code, site, status, lines, buttons).
- Tick box on a row: shown only on Approved and Partly ordered indents. Tick one or more to order them together. {perm: po.edit}
- **Create RFQ (n)**: shown once you tick indents; n is how many. Opens **Request for quotation**. {perm: po.edit}
- **Create PO**: shown once you tick indents. Opens **New purchase order** with the still-to-order product lines of the ticked indents. {perm: po.edit}
- **New indent**: opens the indent form. {perm: indent.create}

**The indent form (New indent / Edit)** {perm: indent.create}
- **Site \***: the site the material is for. Only your sites are listed. It cannot be changed after the indent is saved. {perm: indent.create}
- **Required by**: the date the site needs it. {perm: indent.create}
- **Priority**: **Normal** or **Urgent**. Urgent indents carry a red **Urgent** badge in the list. {perm: indent.create}
- **Remark**: free text for the buyer. {perm: indent.create}
- **Product**, **Qty**, **Unit**: one card per material. The unit starts as the product's unit; another unit is converted to the stock unit. {perm: indent.create}
- **Not in the product list (flagged for the buyer)**: tick it to type the material in **Material (not in the product list)**. The line shows **Not in master** to the buyer. {perm: indent.create}
- **×**: removes that material line. {perm: indent.create}
- **+ Add material**: adds another line. {perm: indent.create}
- **Save draft**: saves it as Draft. Nobody else acts on a draft. {perm: indent.create}
- **Submit for approval**: saves it as Submitted, ready for the approver. {perm: indent.create}
- **Cancel**: closes the form without saving. {perm: indent.create}
- Lines without a quantity, or without a product or text, are dropped when saving. {perm: indent.create}

**Inside an indent**
- The table shows per material: **Asked** (as typed), **In stock unit**, **Ordered** and **Received**.
- **Edit**: shown while the indent is Draft or Submitted, to whoever raised it or anyone who may raise indents for that site. Opens the same form. {perm: indent.create}
- **Submit**: shown on a Draft. Moves it to Submitted. {perm: indent.create}
- **Cancel indent**: asks "Cancel <code>?" and sets the indent to Cancelled. {perm: indent.create, indent.approve}
- **Reject**: asks "Why is it rejected?". With a reason the indent becomes Rejected and shows "Rejected: <reason>". Without a reason nothing happens. {perm: indent.approve}
- **Approve**: sets the indent to Approved. The store / purchase person of the site is told to place the PO. {perm: indent.approve}
- **Create PO**: on an Approved or Partly ordered indent. Opens **New purchase order** for this indent. {perm: po.edit}

**The Request for quotation dialog** {perm: po.edit}
- It asks for what the ticked indents still need. Only product lines go in; lines typed as "not in the product list" are left out. {perm: po.edit}
- Tick the vendors to ask. **Quotes due by**: the date the quotes are due. {perm: po.edit}
- **Create RFQ**: greyed until at least one vendor is ticked. Makes the RFQ and opens it. {perm: po.edit}

**Rules**
- Only Draft and Submitted indents can be edited. After approval the lines are fixed.
- Only a Submitted indent can be approved or rejected, and only by an approver who covers that site. {perm: indent.approve}
- A rejected indent stays rejected. Raise a new indent for the corrected need.
- An indent cannot be raised for a closed site.
- Only Approved and Partly ordered indents can go to an RFQ or a PO. {perm: po.edit}
- Submitting an indent sends no message. Approvers see it in the list with status Submitted. {perm: indent.approve}

**What happens next**
- Approve: the status becomes Approved and the "Indent approved, place the PO" message goes to the store / purchase role of the site. If no PO is made within 24 hours, planning is told.
- When a PO for the indent is approved, the indent's **Ordered** quantity goes up and the status becomes Partly ordered or Ordered.
- When the material is received on an approved GRN, **Received** goes up. When everything is received the indent is Closed.

**Hands off**
- Receives: material needs from the site engineer, site supervisor or planning (also from site material requests and the material plan).
- Passes on: approved indents to the store / purchase role, who makes the RFQ or the PO.

**When it goes wrong**
- "You cannot raise an indent for <site code>": the site is not one of yours. Ask for the site to be assigned to you.
- "<site code> is closed": the site is closed; no new indents.
- "You cannot change <code>" / "You cannot submit <code>": the indent is no longer Draft or Submitted, or it is not yours.
- "You cannot approve <code>": your role does not cover that site.
- "<code> is approved" (or another status): someone already acted on it. Close and reopen the indent.
- "You cannot cancel <code>": only the person who raised it, or an approver, may cancel it. The button can show for others who may raise indents on the site; ask the one who raised it.
- "<code> is <status>; only approved indents are ordered": one of the ticked indents is not approved (any more). Untick it. {perm: po.edit}
- "Nothing left to order on these indents (lines not in the product master are bought with a direct PO)": everything is already ordered, or only typed lines are left. Add the product to the master and order it on a PO. {perm: po.edit}
- An approved indent cannot be cancelled from this page: the **Cancel indent** button is not shown once it is approved.
