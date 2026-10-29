---
page: /payables
title: Payables
routes: /payables
mark: New bill
---
What we owe vendors and subcontractors. Vendor bills are matched against their PO and GRNs, then
approved and paid. Payments above the approval limit wait for an approver. Subcontractor RA bills
are made from verified work-order measurements. The page has five tabs: **Vendor bills**,
**Payments**, **Due this week**, **Ageing** and **Subcontractor bills**.

**On the page**
- **Vendor bills** (tab): every vendor bill, newest bill date first. It shows **Number** (with the kind: material, service, freight, subcontract or retention), **Vendor / bill** (the vendor's bill number and the GRNs on it), **Total**, **TDS** (with the TDS section), **Payable**, **Outstanding**, **Due** and **Status** (draft, approved, partly paid, paid, cancelled).
- A line starting with ⚠ under a bill is a difference from the PO / GRN beyond the match tolerance (quantity or rate). It must be accepted when the bill is approved.
- A line starting with ⛔ and the badge **blocked: 3-way match** mean the bill cannot be approved: it bills more than was confirmed received, or a rate above the PO rate or the vendor's rate contract. When released, the line shows "Released by ... on ...: reason".
- **waiting for director** (badge): a blocked bill that you cannot release yourself. {perm: payables.view}
- **Release**: on a blocked bill. Asks "Release this bill for approval despite the match: why?". Type a reason of at least 5 characters. The bill can then be approved; the reason and your name are kept on the bill. {perm: delivery.escalate}
- **Approve** (on a draft vendor bill that is not blocked): approves the bill for payment. If the bill has ⚠ differences, the app asks "Accept the differences flagged on this bill?". Press OK to accept them and approve. {perm: payables.edit}
- **Payments** (tab): **Number**, **Date**, **Vendor**, **Mode** (with the reference), **Amount**, **Bills** paid and **Status** (paid, pending approval).
- **Approve** (on a payment that is pending approval): approves the payment. It becomes paid and the bills it pays are reduced. {perm: payables.approve}
- **Due this week** (tab): approved bills with money left to pay that fall due in the next 7 days, and every overdue one, oldest due date first. An overdue date is shown in red.
- **Ageing** (tab): what is owed to each vendor by days past the due date: **Not due**, **0-30 days late**, **31-60 days late**, **61-90 days late**, **90+ days late** and **Total**. Largest total first.
- **Subcontractor bills** (tab): each subcontractor RA bill with **Number**, **WO**, **Gross**, **Retention**, **TDS**, **Material** (material recovery), **GST**, **Net** and **Status**. An approved bill shows the number of the vendor bill made from it.
- **productivity low: actual / expected sqm per man-day** (badge): the labour check found the work done per man-day too low. "(overridden)" is added once it was overridden; hover to see the note.
- **productivity norm to be set** (badge): no expected output is set for this kind of work, so the check could not be made.
- **Bill WO-code (subcontractor)**: one button for each active or completed work order. It makes an RA bill from every verified measurement on that work order not billed before. {perm: payables.edit}
- **Override**: on a draft subcontractor bill flagged productivity low. Asks "Override the labour check: note". Type at least 5 characters. The bill can then be approved. {perm: labourcheck.override}
- **Approve** (on a draft subcontractor bill): approves the RA bill and makes an approved vendor bill (kind subcontract) for its net, ready to pay. {perm: payables.edit}
- **New bill**: opens the **Vendor bill** form. {perm: payables.edit}
- **Pay**: opens the **Payment** form. {perm: payables.edit}

**Vendor bill (the form)** {perm: payables.edit}
- **Vendor \***: the vendor or subcontractor. {perm: payables.edit}
- **Kind**: **Material (from GRNs)**, **Service** or **Transporter freight**. {perm: payables.edit}
- **Vendor's bill no \***: the number on the vendor's bill. {perm: payables.edit}
- **Bill date \***: today unless you change it. {perm: payables.edit}
- **Due (blank: payment terms)**: leave blank to use the vendor's payment terms (30 days when none are set). {perm: payables.edit}
- **TDS % (blank: by vendor type)**: leave blank to let the app work out TDS from the vendor type, the PAN and the year's thresholds. A rate typed here is applied to the whole bill. {perm: payables.edit}
- **GRNs not billed yet** (Material): the vendor's approved GRNs that are not on a bill. Tick each GRN the bill covers. Its lines show **Accepted** and **PO rate**. Type **Billed qty** or **Billed rate** only when the vendor billed something different. {perm: payables.edit}
- **Lines** (Service, Transporter freight): **Description**, **Qty**, **Rate** and **GST %** for each line. **+ Line** adds a line. {perm: payables.edit}
- **Save bill**: saves the bill as a draft and runs the three-way match. **Cancel** closes the form. {perm: payables.edit}

**Payment (the form)** {perm: payables.edit}
- **Vendor**: only vendors with approved bills that still have money left to pay. {perm: payables.edit}
- **Mode**: neft, rtgs, cheque, upi or cash. **Ref**: the bank or cheque reference. **From bank**: our bank account. {perm: payables.edit}
- The vendor's open bills are listed with the outstanding amount. Type the amount to pay against each bill in **pay**. Part payments are fine. {perm: payables.edit}
- **Pay**: records the payment for the total of the amounts typed. **Cancel** closes the form. {perm: payables.edit}

**Rules**
- A bill is checked against its PO and GRNs. Differences beyond the **Three-way match tolerance %** (Settings > Finance, 1 % unless changed) are flagged ⚠ and must be accepted to approve the bill.
- A bill that bills more than was confirmed received, or a rate above the PO rate or the rate contract, is blocked. Only a role with release rights can release it, with a reason. Accounts sees "waiting for director".
- A GRN can be on one bill only. The same vendor bill number cannot be entered twice for a vendor.
- Only approved or partly paid bills can be paid. You cannot pay more than what is left, counting payments that are still waiting for approval.
- A payment above the **Payment approval limit (₹)** (Settings > Finance, ₹1,00,000 unless changed) waits for approval, unless you hold the approval right yourself. Then it is paid at once. {perm: payables.edit}
- A subcontractor bill flagged productivity low cannot be approved until it is overridden with a note.
- Subcontractor bill deductions come from the work order: retention %, TDS %, the material we issued to them (when the work order says material by us) and GST at 18 % when the subcontractor is GST registered.
- A paid payment cannot be cancelled here. It is reversed in Tally.

**What happens next**
- **Save bill**: the bill is a draft. If it is blocked, it appears on the director's My work as "Blocked by the three-way match: release with a reason or wait", and on accounts' My work as "waiting for the director".
- **Approve** on a vendor bill: the bill becomes approved and appears in the **Pay** form, **Due this week** and **Ageing**. No one is notified.
- **Pay**: the payment is paid (or pending approval above the limit). The bills turn partly paid or paid. Paid payments go to the Tally export.
- A payment pending approval is not on anyone's My work and sends no message. Tell the approver. {perm: payables.edit}
- **Bill WO-code**: the RA bill is a draft. Billing gets "Labour bill ... check it against the work done" (Check). If productivity is low, the director also gets "productivity low ... Decide." and the bill appears on the director's My work.
- **Approve** on a subcontractor bill: an approved vendor bill (kind subcontract) is made, due after the subcontractor's payment terms (15 days when none are set). Pay it from **Pay**.

**Hands off**
- Receives: approved GRNs from stores; verified measurements from the site; the labour check from billing; releases and overrides from the director.
- Passes on: paid payments and approved bills to the Tally export; vendor dues to Site profit.

**When it goes wrong**
- "Bill GRNs, or give the lines of a direct bill": for Material, tick at least one GRN; for Service or Freight, fill a line with a description and a rate.
- "... 's bill ... is already entered": this vendor bill number is already in the app. Check the list.
- "GRN-code is ...: bill approved GRNs" or "GRN-code is already billed": pick another GRN; a GRN must be approved and not on another bill.
- "Blocked by the three-way match: ... Accounts can release it with a reason (delivery.escalate).": the bill is blocked. Ask the director to release it, or get a correct bill from the vendor.
- "The bill does not match the PO / GRN: accept the differences to approve it": you pressed Cancel on "Accept the differences flagged on this bill?". Press **Approve** again and OK, or get a corrected bill.
- "VB-... is draft: approve it first" (or cancelled): approve the bill before paying it.
- "...: ... is more than what is left to pay": lower the amount. A payment still waiting for approval counts as paid here.
- "Payments above ₹... need payables.approve": only an approver can approve this payment.
- "No verified, unbilled measurements": nothing on the work order is verified and not billed yet. Ask the site to have the measurements verified.
- "Recoveries exceed the bill": the retention, TDS and recoveries are more than the bill. Check the material issued and the work order terms.
- "Productivity low: ... Approval needs labourcheck.override with a note.": the director must **Override** the bill first.
- **Release** or **Override** does nothing: the reason or note was shorter than 5 characters, or you pressed Cancel. Press it again and type a longer reason.
