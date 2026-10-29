---
page: /settings/purchase
title: Purchase settings
routes: /settings/purchase
mark: Save
---
The company-wide purchase rules: the PO approval limit, how many approvals a GRN needs, the
default terms printed on POs, and whether stock may go below zero. Purchase sees the settings;
only the company settings right changes them. Every save is written to the audit log.

**On the page**
- **PO approval limit (₹)**: the hint under it reads "Up to ₹<limit> the buyer approves their own PO; above it a PO approver must."
- **GRN approvals**: **One approval**, or **Two approvals (by two people)**.
- **PO terms & conditions template**: **Built-in purchase terms**, or one of the T&C templates from the T&C library.
- **Allow stock to go below zero**: when ticked, a store may issue more than it holds.
- **Save**: saves the settings. "Saved." shows when it worked. {perm: settings.company}
- Without the company settings right the fields are greyed and there is no **Save**.

**Rules**
- The PO limit is compared with the PO's grand total. A PO at or under the limit can be approved by the buyer who made it. Above the limit, only a role with the PO approve right can approve it.
- With two GRN approvals, the second approval must be by a different person. The material goes into stock only at the last approval.
- The GRN setting is fixed on each GRN when it is made. GRNs already made keep their number of approvals.
- With **Allow stock to go below zero** off, an issue or transfer of more than the store holds is refused.

**What happens next**
- New POs above the limit wait for a PO approver.
- New GRNs need one or two approvals.
- New POs print the chosen terms.

**Hands off**
- Receives: the approval limits agreed by the director.
- Passes on: the rules purchase, stores and the PO approvers work under.

**When it goes wrong**
- "T&C template not found": the template was removed. Pick another one and save.
- A negative limit is refused next to the field. Type 0 or more.
- "Only <qty> <unit> of <product> in <store>; <qty> asked": shown on stores pages when the box is unticked and the stock is short.
