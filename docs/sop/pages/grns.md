---
page: /grns
title: Goods receipts (GRN)
routes: /grns
mark: New GRN
---
The list of goods receipts (GRNs): what arrived, against which PO (or **direct** for a purchase
without a PO), the vendor, the store, the invoice no and the status. A GRN puts material into
stock only when it is approved. One or two approvals are needed, as set in Settings › Purchase
(**GRN approvals**).

**On the page**
- **Status** (filter): **All statuses**, draft, submitted, approved, rejected.
- The **Status** column shows "n/2" beside Submitted when two approvals are needed.
- A row: opens the GRN.
- **New GRN**: opens the GRN form. {perm: grn.edit}

**The GRN form (New GRN / Receive against <PO>)** {perm: grn.edit}
- **Against**: **— pick a PO —** lists the Approved, Sent and Partly received POs; or **Direct purchase (no PO)**. Opened from **Receive (GRN)** on a PO, the PO is already set. {perm: grn.edit}
- **Vendor \***: only for a direct purchase. {perm: grn.edit}
- **Received into \***: the store the material goes into. For a PO it starts at the PO's store. {perm: grn.edit}
- **Received on**: today by default. {perm: grn.edit}
- **Challan no**, **Vehicle no**, **Invoice no**, **Invoice date**, **Invoice amount (₹)**, **Remark**: from the vendor's papers. {perm: grn.edit}
- Material: for a PO, one card per line still pending ("pending n unit"). **Received** starts at the pending quantity. {perm: grn.edit}
- For a direct purchase: **Product**, **Unit** and **Rate (net)** on each card; **+ Item** adds a card. {perm: grn.edit}
- **Received**, **Rejected**: what came and what you refuse. **Accepted** = received − rejected, worked out. {perm: grn.edit}
- **Reason for rejection \***: appears when **Rejected** is more than 0. Required. {perm: grn.edit}
- Cards with **Received** 0 or empty are left out. {perm: grn.edit}
- **Save draft**: saves it as Draft. {perm: grn.edit}
- **Submit for approval**: saves it as Submitted, ready for the approver. {perm: grn.edit}
- **Cancel**: closes without saving. {perm: grn.edit}
- Photos are added after saving, from inside the GRN. {perm: grn.edit}

**Inside a GRN**
- The status, the PO (or "direct purchase"), the store, the date and "approvals n/2" when two are needed.
- Challan, invoice (no, date, amount) and vehicle.
- The table: **Pending** (on the PO when received), **Received**, **Accepted**, **Rejected** (with the reason under the item), **Rate** and **Landed / base unit** (filled in on approval).
- **Photos**: the photos and PDFs added, each with its kind.
- **Photo of**: **Material**, **Challan** or **Invoice**. Then **Choose photos** to add photos or PDFs (camera on a phone). Shown until the GRN is approved. {perm: grn.edit}
- **Submit**: on a Draft. Moves it to Submitted. {perm: grn.edit}
- **Reject**: on a Draft or Submitted GRN. Asks "Why is the GRN rejected?". With a reason it becomes Rejected and shows "Rejected: <reason>". Nothing goes into stock. {perm: grn.approve}
- **Approve: put in stock**: the last approval. Sets it to Approved and puts the accepted quantity into the store. {perm: grn.approve}
- **Approve (level 1)**: shown instead when two approvals are needed and none is given yet. The GRN stays Submitted for a second person. {perm: grn.approve}

**Rules**
- A GRN against a PO is only for an Approved, Sent or Partly received PO. {perm: grn.edit}
- You cannot accept more than is still pending on the PO. Short or extra material goes in **Rejected** with a reason. {perm: grn.edit}
- With two approvals, the second must be by someone else. {perm: grn.approve}
- The stock rate is the PO rate after discount, plus the PO charges ticked **Add to material cost**, shared by value. A direct purchase uses the **Rate (net)** typed in.
- An approved GRN cannot be changed or rejected, and no photos can be added to it.
- A saved GRN cannot be edited on screen. If something is wrong, have the approver reject it and make a new one.
- No message is sent when a GRN is submitted. Approvers see it in the list with status Submitted. {perm: grn.approve}

**What happens next**
- Approve: the accepted quantity enters the store's stock at the landed rate. The PO's **Received** goes up and the PO becomes Partly received or Received. The indents' **Received** goes up; a fully received indent is Closed.
- The PO's freight is charged to the sites in proportion to the value received.
- A material test planned for the site in its methodology becomes due.
- Accounts match the vendor's bill against the approved GRN quantities (three-way match on Payables).

**Hands off**
- Receives: the delivery at the godown or the site, against a PO sent by the store / purchase role.
- Passes on: the approved receipt to the store's stock, and to accounts for the vendor bill.

**When it goes wrong**
- "<PO code> is <status>; material is received against an approved PO": the PO is still Draft or Pending approval, or already Closed. Ask for it to be approved, or use a direct purchase. {perm: grn.edit}
- "<item>: n unit accepted but only m pending on <PO code>": you are accepting more than is still due. Put the extra in **Rejected** with a reason. {perm: grn.edit}
- "Accepted + rejected cannot be more than received": fix the quantities. {perm: grn.edit}
- "Give the reason for the rejected quantity": fill in **Reason for rejection \***. {perm: grn.edit}
- "A direct purchase needs the vendor and the store" / "A direct purchase line needs the product and its rate": fill in **Vendor \***, **Received into \***, the product and **Rate (net)**. {perm: grn.edit}
- "You cannot receive material in <store>": your role does not cover that store. {perm: grn.edit}
- "<GRN code>: the second approval must be by someone else": ask the other approver. {perm: grn.approve}
- "You cannot approve <GRN code>" / "You cannot reject <GRN code>": your role does not cover that store. {perm: grn.approve}
- "Upload a photo (.jpg, .png, .webp, .heic) or a PDF" / "The file is larger than 15 MB": pick another file, or make it smaller. {perm: grn.edit}
- "You cannot add photos to <GRN code>": the GRN is approved, or the store is not yours. {perm: grn.edit}
