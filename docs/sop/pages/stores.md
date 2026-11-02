---
page: /stores
title: Stores & stock
routes: /stores, /stores/:id
mark: Add godown
---
The list of stores you can see: the godowns and the store of each site. Each row shows the kind
(**Godown** or **Site store**), how many products are in stock and the stock value. Click a row to
open the store: its stock, its ledger, its transfers and what was issued to work or returned.
Site roles see only the stores of their own sites.

**On the page (the list)**
- **Transfers**: opens the Transfers page.
- **Add godown**: opens **Add a godown**. Type the **Name** and press **Add**. A site store is never added here: it is made with its site. Shown only to roles that edit every store (not to a role that edits only its sites' stores). {perm: store.edit}
- **Store**, **Kind**, **Items in stock**, **Stock value** (columns): click a row to open that store.

**On the page (one store)**
- The header shows the kind, the stock value and, for a site store, a link to the site.
- **Transfer out**: opens **Transfer material** with this store as **From**. See the Transfers page for the fields. {perm: store.edit}
- **Issue to work**: only on a site store. Opens **Issue material to work**: material used on the site leaves the store at its average rate. {perm: store.edit}
- **Return to store**: only on a site store. Opens **Return unused material to the store**: unused material comes back in at the store's average rate. {perm: store.edit}
- **Adjust / opening**: opens **Opening stock or count correction**. Shown only to roles that edit every store. {perm: store.edit}
- **Stock** (tab): each product with its **Stock**, **Avg rate (landed)** and **Value**. A row below zero is shown flagged.
- **Ledger** (tab): every movement, newest first: **When**, **Product**, **Movement** (GRN, Transfer out, Transfer in, Issued to site, Returned, Adjustment, Opening, or shortage), **Ref**, **Qty**, **Rate**, **Value** and the running **Balance** of that product. Pick a product in the box above the table to see only its rows.
- **Transfers** (tab): the transfers into and out of this store, with **Dispatch** and **Receive** as on the Transfers page.
- **Issues & returns** (tab): each issue and return: **Code**, **Date**, **Kind**, **For** (the task), **Items** and **Value**.

**Issue material to work / Return unused material to the store**
- **For task** (issue only): the task of the site the material was used on. The first choice is **— general site use —**.
- **Area used on** (issue only, with **— general site use —** on a site with a list): the place on the site's list the material was used on, or a new area waiting for planning ("(new area, waiting)"). Required.
- **Date**: today unless you change it. **Remark**: free text.
- Product lines: **Product**, **Qty**, **Unit**, **×** removes a line, **+ Item** adds one. Lines with no product or a zero quantity are dropped.
- **Issue** / **Return**: saves it and gives it an ISS code. Stock moves at once. **Cancel** closes the form.

**Opening stock or count correction**
- **Product** (required), **Kind** (**Opening stock** or **Count correction**).
- **Qty (+ in / − out, in the product's unit)**: a plus number adds stock, a minus number takes it out.
- **Rate (for stock added)**: needed when the quantity is plus. A minus quantity goes out at the store's average rate.
- **Note \***: why. It is kept on the ledger row and in the audit log.
- **Save**: posts the ledger row at once. {perm: store.edit}

**Rules**
- Stock is kept in each product's own unit. A line in another unit is converted; the product needs a unit conversion for that.
- Stock cannot go below zero, unless the company allows negative stock in its settings.
- Issue to work: on a site that has its list of areas (its structure), the material must be booked on a task of that list.
- Only roles with company-wide store rights can add a godown or adjust stock. Site roles who can edit their site store can issue, return and transfer, but not adjust. {perm: store.edit}
- Stock values are at the landed average rate (rate plus the PO's charges added to material cost).

**What happens next**
- A GRN approved on the Goods receipts page puts stock into the store (Movement "GRN").
- An issue is charged to the site as material used. A return reduces it.
- A transfer dispatched from here takes stock out at the average rate; see the Transfers page.

**Hands off**
- Receives: stock from goods receipts approved by store and purchase, and from transfers.
- Passes on: material issued to work on the site; transfers to other stores; the stock value to the site's cost.

**When it goes wrong**
- "Store not found": the store is not one of your sites' stores, or it was removed. Open it from the list.
- "A store named ... exists": pick another name for the godown.
- "You cannot add a godown" / "You cannot adjust stock": your role edits only your sites' stores (the buttons are hidden for it). Ask store and purchase. {perm: store.edit}
- "Give a quantity": the quantity is zero.
- "Give the rate of the stock added": a plus quantity needs a rate.
- "Only ... of ... in ...; ... asked": there is not enough stock. Check the ledger, receive the GRN or transfer first, or correct the count.
- "Pick the area it was used on (from the site's list), or ask for a new area": on a site with a list, **— general site use —** needs the place. Pick it in **Area used on**, or pick the task in **For task**.
- "That task is not on this site": pick a task of this site.
- "...: ... cannot be converted to ... (add a unit conversion for this product first)": use the product's own unit, or have the conversion added.
- "You cannot issue material in ...": the store is not on one of your sites.
