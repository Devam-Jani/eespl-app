---
page: /freight
title: Site freight
routes: /freight
mark: Add transporter bill
---
Transport costs charged to each site, per month. The top table splits each site and month into
**Inbound** (vendor to us), **Godown → site** and **Other**, with a **Total** row. Below it,
**Entries** lists each charge: **Date**, **Site**, **Source**, **Direction**, **Transporter** and
**Amount**. You see the sites you can see; a row with no site is godown freight.

**On the page**
- **Site** (filter): **All sites** or one site. Changes both tables.
- **Year** (filter): the year of the top table and of the **Entries** list below (its latest 200 entries).
- **Add transporter bill**: opens **Transporter bill**, for a transport bill that is not on a PO or a transfer. {perm: po.edit, store.edit}

**Transporter bill (the form)**
- **Charge to site \***: the site that bears the cost.
- **Direction**: **Inbound (vendor → us)**, **Godown → site** or **Other**.
- **Date**: today unless you change it.
- **Amount (₹) \***: more than zero.
- **GST %**: 0 to 28.
- **Bill no**, **Transporter**, **Vehicle no**, **Remark**.
- **Save**: adds the entry (Source "Transporter bill"). **Cancel** closes the form.

**Where the other entries come from**
- **PO charge**: a PO's freight charge is spread over the sites as its goods are received. Each GRN carries the share of the freight that its received value bears to the PO value.
- **Transfer**: the freight typed on a transfer is charged to the receiving site when the transfer is received.

**Rules**
- You can charge a bill only to a site you can buy or store for. Company-wide roles can charge any site. {perm: po.edit, store.edit}
- An entry cannot be changed or deleted on this page.

**Hands off**
- Receives: freight from POs (through GRNs) and from transfers; transporter bills from store and purchase.
- Passes on: the freight cost to each site's cost and profit.

**When it goes wrong**
- "Site not found": pick the site again.
- "You cannot charge freight to ...": the site is not one of yours. Ask store and purchase.
- "No freight recorded.": nothing for this site and year. Check the **Year**.
