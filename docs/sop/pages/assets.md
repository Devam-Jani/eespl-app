---
page: /assets
title: Tools & equipment
routes: /assets
mark: Add asset
---
The register of tools, equipment, machines and vehicles: where each one is, since when, and what
its use costs each site. Each row shows the **Code** (AST...), the **Asset** with its category,
make, model and the vendor for a hired one, **Where** it is and for how many days, the **Status**
(available, at site, repair, lost, disposed) and the **Rate**. Site roles see only the assets at
their own sites.

**On the page**
- **Where is everything** (tab): every asset you can see.
- **Overdue at sites** (tab): assets kept at a site longer than the company's limit (30 days unless changed in the company settings). Their days show in red.
- **Equipment cost** (tab): per site, the number of use **Entries**, the **Fuel** cost and the total **Cost**; below it, **Usage (90 days)**: each logged use with its date, site, asset, days or hours × rate, fuel, operator and cost.
- **Add asset**: opens **Add an asset**. {perm: asset.edit}
- **Move** (on a row): opens **Move ...** to issue the asset to a site or return it to a store. {perm: asset.edit}
- **Log use** (on a row): only for an equipment, machine or vehicle that is at a site. Opens **Use of ...**. {perm: asset.edit}

**Add an asset (the form)**
- **Name \***, **Category** (tool, equipment, machine, vehicle), **Make**, **Model**, **Serial no**.
- **Ownership**: **Own** or **Hired**. A hired asset needs **Hired from \***, the vendor.
- **Purchase date**, **Purchase value (₹)**.
- **Rate per day (₹)**, **Rate per hour (₹)**: what a day or an hour of use costs the site.
- **Add (kept in the godown)**: adds it with status available, in the godown, from today. **Cancel** closes the form.

**Move (the form)**
- It shows where the asset is now.
- **To \***: **Return to a store** (a godown) or **Issue to a site**. An asset at a site starts on the godown.
- **Date**: today unless you change it. **Condition**: for example "Good" or "needs service".
- **Photo**: take or attach a photo of the asset.
- **Move**: moves it. Issued to a site its status becomes at site; returned to a store it becomes available. An asset in repair stays in repair.

**Use of ... (the form)**
- **Date**; **By**: **Days** or **Hours**.
- **Days \*** / **Hours \***: how much it was used (more than zero, at most 744).
- **Rate (blank: ...)**: leave blank to use the asset's own rate per day or hour.
- **Fuel (litres)**, **Fuel cost (₹)**, **Operator**.
- **Cost**: days or hours × rate + fuel cost, worked out as you type.
- **Save**: books the cost to the site. **Cancel** closes the form.

**Rules**
- Only roles with company-wide asset rights keep the register and move assets. {perm: asset.edit}
- An asset at a site cannot be issued straight to another site: return it to a store first.
- A lost or disposed asset cannot be moved.
- Use can be logged only for the site where the asset is now.

**What happens next**
- The use cost (with fuel) is added to the site's equipment cost, which shows in the site's budget against actual.

**Hands off**
- Receives: requests from the site for a tool or machine.
- Passes on: the asset to the site; its use cost to the site's cost.

**When it goes wrong**
- "The asset register needs asset.edit (all)": your role cannot change the register. Ask store and purchase.
- "A hired asset needs the vendor it is hired from": pick **Hired from**.
- "Move it to a site or to a store": pick **To**.
- "... is lost" / "... is disposed": it cannot be moved.
- "... is already at ...": it is at that site already.
- "... is at ...; return it to a store first": return it, then issue it to the new site.
- "... is already in that store": pick another place.
- "... is not at ...: issue it to the site first": move it to the site, then log the use.
- "... has no rate per day" / "... has no rate per hour": type the **Rate**.
- "Asset not found": it is not at one of your sites.
