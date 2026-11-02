---
page: /rfqs
title: Requests for quotation
routes: /rfqs, /rfqs/:id
---
The list of RFQs: asking several vendors for their rates on what approved indents still need.
Each row shows the code, the indents, the vendors asked, the number of lines, the due date and the
status. An RFQ is started from the Indents page (Indents › pick › Create RFQ), not from here.

**On the page**
- A row: opens the RFQ's comparison grid.
- The page has no **New** button. To start one, tick approved indents on **Indents** and press **Create RFQ (n)**.

**Inside an RFQ (the comparison grid)**
- One row per item, one column per vendor. Each vendor column shows **Freight (total)** and **Landed total**.
- Landed rate = rate + the line's share of the vendor's freight (shared by value). It is worked out only after the quotes are saved.
- The cell with the lowest landed rate is marked **lowest**.
- **RFQs** (breadcrumb): back to the list. The links **#n** after "POs" open the POs made from this RFQ.
- **<vendor> rate** and **<vendor> GST** (fields in each cell): type the vendor's rate and GST %. GST starts at 18. {perm: po.edit}
- **Freight (total)** (field under the vendor name): the vendor's total freight for the order. {perm: po.edit}
- **Save quotes**: saves every typed rate and freight. The status moves from Draft to Sent. Nothing is sent to the vendors; the quotes are typed in from what they sent you. {perm: po.edit}
- Radio button in a cell (shown once that quote is saved): picks that vendor for the line. It is saved at once. The lowest landed rate is picked unless you pick another. {perm: po.edit}
- Picking a vendor that is not the lowest asks "This is not the lowest landed rate. Why this vendor?". Without a reason nothing is picked. The reason shows under the item as "Picked over the lowest: <reason>". {perm: po.edit}
- **Deliver to**: **Deliver to: the indent's store**, or one store from the list. {perm: po.edit}
- **Make PO(s) from the picks**: makes one draft PO per picked vendor and closes the RFQ (and the "Indent approved, place the PO" task of its indents). With one PO it opens that PO; with more it opens the PO list. {perm: po.edit}
- Once closed, the grid is read-only and shows **picked** on the chosen vendor.

**Rules**
- A line with no pick takes the vendor with the lowest landed rate. {perm: po.edit}
- Each PO gets the vendor's freight as a **Freight** charge, added to the material cost. {perm: po.edit}
- A vendor without a GSTIN gets 0 % GST on its PO lines. {perm: po.edit}
- With **Deliver to: the indent's store**, the POs go to the indents' store when all the indents share one; otherwise to the godown. {perm: po.edit}
- The POs are drafts. They still need **Approve** or **Send for approval** on the PO page, under the approval limit. {perm: po.edit}
- A closed or cancelled RFQ cannot be changed.

**What happens next**
- The draft POs appear on **Purchase orders** with a link back to the RFQ. Approve them there.

**Hands off**
- Receives: approved indents from the indent approver.
- Passes on: draft POs to the PO approver (above the limit) or to yourself (within the limit).

**When it goes wrong**
- "<item>: no vendor has quoted": a line has no saved rate. Type a rate and press **Save quotes** first. Typed rates that are not saved are not used. {perm: po.edit}
- "<item>: give a reason for not taking the lowest landed rate": the reason prompt was left empty. {perm: po.edit}
- "That vendor has not quoted this line": save that vendor's rate before picking it. {perm: po.edit}
- "<RFQ code> is closed": POs were already made from this RFQ. Open them from the **#n** links. {perm: po.edit}
- "You cannot order material in <store>": your role does not cover the store chosen in **Deliver to**. Pick another store. {perm: po.edit}
- "<item>: above agreed rate by n% (contract ₹x per unit): give the reason": the vendor has a rate contract lower than the quote. Make the PO from the Indents page with a reason, or pick the contract vendor. {perm: po.edit}
