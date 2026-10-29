---
page: /purchase-orders
title: Purchase orders
routes: /purchase-orders, /purchase-orders/new, /purchase-orders/:id
mark: New PO
---
The list of purchase orders (POs): PO no, date, vendor, the store it is delivered to, the grand
total and the status. A PO is made from approved indents, from an RFQ, or by hand. Up to the
approval limit (Settings › Purchase) the buyer approves their own PO; above it a PO approver must.

**On the page**
- **Search PO no or vendor**: type and press Enter.
- **Status** (filter): **All statuses**, or draft, pending approval, approved, sent, partly received, received, closed, cancelled.
- A row: opens the PO.
- **New PO**: opens **New purchase order**. {perm: po.edit}

**New purchase order (also Edit)** {perm: po.edit}
- Opened from **Create PO** on Indents, the form already holds the indents' still-to-order product lines and, for one indent, its store. {perm: po.edit}
- **Vendor \***: the supplier. The line below says "Supplier unregistered: no GST, no input tax credit", "Inter-state supply: IGST" or "Intra-state supply: CGST + SGST". {perm: po.edit}
- **Deliver to \***: the store the material goes to (the godown, or a site store). {perm: po.edit}
- **Bill from (our GSTIN)**: our GSTIN address on the PO. {perm: po.edit}
- **PO date**: today by default. It cannot be changed when editing. {perm: po.edit}
- **Expected delivery**, **Payment terms**, **Remark**. Left blank, **Payment terms** takes the vendor's credit days ("n days from the invoice"). {perm: po.edit}
- Lines: **Product**, **Qty**, **Unit**, **Rate**, **Disc %**, **GST %**; **Taxable** is worked out. **×** removes a line. **+ Line** adds one. {perm: po.edit}
- **Rate**: when the vendor has a rate contract for the product, the field shows "contract" and the contract rate is shown below. Left blank, the contract rate is used. {perm: po.edit}
- A rate above the contract turns red with "+n %" and asks "why above the contract?". The reason is required. {perm: po.edit}
- Under the rate: the last price used for the product ("Last ₹x/unit on date by ..."), flagged when the new rate differs by more than the set percentage. {perm: po.edit}
- Charges: **Kind** (freight, loading, unloading, packing, other), **Description**, **Amount**, **GST %**, **Add to material cost**. **+ Charge** adds a freight line. {perm: po.edit}
- The totals box: **Sub total**, **Less discount**, **Taxable value**, **Charges**, **CGST** and **SGST** (or **IGST**), **Round off**, **Grand total**. {perm: po.edit}
- Under the totals: "Within the approval limit (₹x): you can approve it yourself." or "Above the approval limit (₹x): it will need a PO approver." {perm: po.edit}
- **Create draft PO** (or **Save** when editing): saves the PO as Draft and opens it. Greyed while there are no lines. {perm: po.edit}
- **Cancel**: leaves without saving. {perm: po.edit}

**Inside a PO**
- The header: vendor (and GSTIN), the store, the date, IGST or CGST + SGST, and a link **RFQ** when it came from one.
- The table: each line with qty (and the indent's unit in brackets when different), rate, the contract rate and "+n %" when above it, the rate reason, discount, taxable, GST and **Received**. Charges follow in grey.
- **Payment terms**, **Expected delivery**, **Created**, **Approved**, **Remark** below the table. Send-back reasons are added to the remark as "Sent back: <reason>".
- **Goods received**: the GRNs against this PO, each linking to the GRN. {perm: grn.view}
- **PDF**: downloads the PO as a PDF.
- **Edit**: shown while the PO is Draft or Pending approval. Saving puts it back to Draft: it must be approved again. {perm: po.edit}
- **Approve** (on a Draft within the limit): approves your own PO at once. {perm: po.edit}
- **Send for approval** (on a Draft above the limit): sets it to Pending approval. The PO then shows "₹x is above the approval limit of ₹y: a PO approver must approve it." {perm: po.edit}
- **Approve** (on a Pending approval PO): approves it. {perm: po.approve}
- **Send back**: asks "Send back to draft: why?". The PO goes back to Draft with the reason in the remark. Without a reason nothing happens. {perm: po.approve}
- **Mark sent**: on an Approved PO. Sets it to Sent. Greyed with "Set the company GSTIN first" while our GSTIN is missing. It does not e-mail the vendor: send the **PDF** yourself. {perm: po.edit}
- **Receive (GRN)**: on an Approved, Sent or Partly received PO. Opens the GRN form for this PO with the pending quantities filled in. {perm: grn.edit}
- **Short-close**: shown once some material is received. Asks "Short-close: why will the rest not come?" and sets the PO to Closed. {perm: po.edit}
- **Cancel PO**: until material is received. Asks "Cancel <code>: why?" and sets it to Cancelled. {perm: po.edit}

**Rules**
- The approval limit is set in Settings › Purchase (**PO approval limit (₹)**). Up to it the buyer's own **Approve** works. Above it only a role with PO approval can approve, even when the buyer holds it too: the PO goes to Pending approval first. {perm: po.edit, po.approve}
- Only Draft and Pending approval POs can be changed. After approval, cancel it and make a new one. {perm: po.edit}
- A PO cannot move to another financial year. {perm: po.edit}
- An unregistered vendor (no GSTIN) cannot charge GST. Its lines start at 0 %. Typing GST anyway shows "This supplier has no GSTIN and cannot charge GST: the GST entered will not be input tax credit." {perm: po.edit}
- Charges with **Add to material cost** ticked (freight by default) are added to the stock rate of the material when it is received.
- Freight on the PO is charged to the sites as the material arrives, in proportion to what each GRN receives.
- Going to Pending approval sends no message. The approver finds it with the **Status** filter set to pending approval. A pending PO with a rate above the contract also appears on the director's My work as "A rate above the vendor's contract, with a reason: approve or not". {perm: po.approve}

**What happens next**
- Approve: the indents' **Ordered** quantity goes up and the indents become Partly ordered or Ordered. The PO appears on the store / purchase My work as "Approved: send it to the vendor".
- Mark sent: the rates go into the price list. When the PO is delivered to a site store, a delivery note is made: the site in-charge and site members get the receipt link, and the site engineer and supervisor are told "Material on the way ... Prepare the surface (cleaning, grinding) before it arrives."
- Receive (GRN): the GRN goes to the GRN approver. When it is approved, **Received** goes up and the PO becomes Partly received or Received.
- Cancel PO on an Approved or Sent PO: the indents' ordered quantity goes back down and the PO's freight entries are removed.

**Hands off**
- Receives: approved indents from the indent approver, and draft POs made from RFQs.
- Passes on: POs above the limit to the PO approver (director, office admin); the sent PO to the vendor; the delivery to the store or the site (delivery note); the receipt to the GRN.

**When it goes wrong**
- "<item>: enter the rate (no rate contract with this vendor)": type the rate. {perm: po.edit}
- "<item>: above agreed rate by n% (contract ₹x per unit): give the reason": fill in "why above the contract?". {perm: po.edit}
- "<item>: the indent line is for another product": a line from an indent was changed to another product. Put the product back or remove the line. {perm: po.edit}
- "You cannot order material in <store>": your role does not cover that store. Pick another **Deliver to**. {perm: po.edit}
- "Add a line first": the PO has no lines. {perm: po.edit}
- "<code> is <status>; it can no longer be changed": the PO is past approval. {perm: po.edit}
- "A PO cannot move to another financial year": make a new PO instead. {perm: po.edit}
- "You cannot approve <code>: above ₹x it needs a PO approver (po.approve)": ask the director or office admin to approve it. {perm: po.edit, po.approve}
- "GSTIN not set: add the company GSTIN in Settings › GSTIN addresses before this PO is sent.": shown in red on the PO. Ask the office admin to add the GSTIN; **Mark sent** stays greyed until then. {perm: po.edit}
- "Supplier unregistered (no GSTIN), but GST is entered on: ... An unregistered supplier cannot charge GST.": edit the PO and set GST to 0. {perm: po.edit}
- "<code> has a GRN; reject it first": a GRN exists against the PO. Have the GRN rejected, then cancel. {perm: po.edit}
- "<code> is <status>; approve it first": **Mark sent** works only on an Approved PO. {perm: po.edit}
