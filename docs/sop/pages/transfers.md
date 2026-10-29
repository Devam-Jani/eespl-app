---
page: /transfers
title: Transfers
routes: /transfers
mark: New transfer
---
Material moved between stores: from the godown to a site, from one site to another, or back.
Each transfer shows its code (TO...), the date, **From → to**, the items sent (with any shortage
and its reason), the **Freight** and the **Status**: draft, dispatched or received. You see the
transfers into or out of the stores you can see.

**On the page**
- **New transfer**: opens **Transfer material**. {perm: store.edit}
- **Dispatch** (on a draft row): sends a saved request. Shown when you can edit the sending store. {perm: store.edit}
- **Receive** (on a dispatched row): opens the receive form. Shown when you can edit the receiving store. {perm: store.edit}

**Transfer material (the form)**
- **From \*** and **To \***: the two stores. The lists show only stores you can see. From starts on the godown.
- **Transporter**, **Vehicle no**: who carries it.
- **Freight (₹, charged to the receiving site)**: the transport cost. It is booked to the receiving site when the transfer is received.
- **Remark**: free text.
- Product lines: **Product**, **Qty**, **Unit**, **×** removes a line, **+ Item** adds one.
- **Dispatch now (stock leaves the sending store)**: ticked, the stock leaves at once. Unticked, the transfer is saved as a draft request for the sending store to dispatch.
- **Dispatch** / **Save request**: the button follows the tick box. **Cancel** closes the form.

**Receive (the form)**
- One card per product, with what was sent.
- **Received**: starts at the quantity sent. Lower it if less arrived.
- **Short by ...: reason \***: appears when you lower **Received**. Say why (broken, short loaded ...).
- **Receive**: completes the transfer.

**Rules**
- From and To must be two different stores.
- You need edit rights on at least one of the two stores to make a transfer, on the sending store to dispatch, and on the receiving store to receive. {perm: store.edit}
- Dispatch takes the stock out of the sending store at its average rate. It cannot go below zero unless the company allows negative stock.
- On receipt, all that was sent comes into the receiving store at the dispatch rate; what did not arrive is then written off there as a shortage. So a shortage is charged to the receiving site.
- You cannot receive more than was sent. A shortage always needs a reason.

**What happens next**
- Dispatch to a site store makes a delivery note (DN...). The site in-charge and the site's members get the receipt link in the app ("... on its way to ...: count it at site"). The site engineer and supervisor are told the material is on the way so they can prepare the surface.
- The site can count it from the receipt link. If the store receives the transfer in the app first, the open delivery note is closed with the received quantities.
- A short receipt raises a discrepancy: store and purchase are notified at once.
- On receipt the freight becomes a "Transfer" entry on the Site freight page for the receiving site.

**Hands off**
- Receives: a request for material from the site (a draft transfer), or the store's own plan.
- Passes on: the delivery note to the site in-charge, supervisor and engineer; the freight and any shortage to the receiving site's cost.

**When it goes wrong**
- "Pick two different stores": From and To are the same.
- "Store not found": a store was removed; reopen the form.
- "You cannot move material from ... to ...": neither store is yours. Ask store and purchase.
- "You cannot dispatch from ...": you cannot edit the sending store.
- "You cannot receive into ...": you cannot edit the receiving store.
- "TO... is dispatched" / "TO... is received": someone else acted on it already. Refresh the page.
- "Only ... of ... in ...; ... asked": the sending store does not have enough stock.
- "...: more received than was sent": lower **Received**.
- "...: give the reason for the shortage": fill in the reason.
- "...: ... cannot be converted to ... (add a unit conversion for this product first)": use the product's own unit.
