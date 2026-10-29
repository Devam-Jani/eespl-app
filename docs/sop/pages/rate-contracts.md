---
page: /rate-contracts
title: Rate contracts
routes: /rate-contracts
mark: New contract
---
The rate agreed with each vendor for each product, per the product's base unit, and the dates it
holds. A new PO line for that vendor and product takes this rate; a higher rate needs a reason.
Each row shows **Vendor**, **Product**, **Rate**, **Valid** (from – till), **Freight** terms and
**Agreed by**. A contract that is not active is shown greyed.

**On the page**
- **In force today** (tick box): ticked, only active contracts valid today are listed. Untick it to see all, including old and future ones.
- **New contract**: opens **New rate contract**. {perm: ratecontract.edit}
- **Edit** (on a row): opens the contract to change it. {perm: ratecontract.edit}
- **v1**, **v2** ... (on a row): the version number. Press it to see every version: the rate, the dates, who saved it and when.
- **⤓ quote** (on a row): downloads the vendor's quote, when one is attached.
- **ends in n d** (badge): the contract ends within 15 days.

**New rate contract / Edit (the form)**
- **Vendor**, **Product**: chosen once. They cannot be changed on an existing contract.
- **Rate per ... (₹)**: the rate per the product's unit. Beside it the app shows the last price used for the product, its date, who entered it and the source; a change of more than the set limit (10 %) is flagged.
- **Freight terms**: for example "delivered to site".
- **Valid from**, **Valid till**: the dates the rate holds.
- **Agreed by**: who agreed it.
- **Vendor's quote (attachment)**: **Choose the quote** attaches the vendor's quote.
- **Notes**: free text.
- **Active** (edit only): untick to end the contract.
- **Save (new version)**: saves and adds a version. Attaching a quote saves one more version. **Cancel** closes the form. {perm: ratecontract.edit}

**Rules**
- Vendor, product, rate, valid from and valid till are all needed. The rate must be more than zero.
- Only one active contract per vendor and product on any date. To change the rate for later dates, end the old contract (shorten **Valid till** or untick **Active**) before adding the new one.
- Every save keeps the old version; nothing is overwritten.
- Each saved rate also goes into the master price list as a "rate contract" price.
- On a PO: a line left at no rate (or zero) takes the contract rate. A rate above it is refused unless a reason is given. Accounts sees the agreed rate on every PO.

**What happens next**
- When a contract is close to its end (15 days by default), store and purchase get a "Rate contract expiring" alert, and a "Renew" item on My work.

**Hands off**
- Receives: the vendor's quote and the agreed rate from purchase talks.
- Passes on: the agreed rate to every PO line for that vendor and product, and to accounts' check of the vendor bill.

**When it goes wrong**
- "Vendor or product not found": no vendor or product is picked, or it was removed. Pick them again.
- An empty **Rate** or date is refused with a message naming the field: fill it in.
- "Valid till is before valid from": fix the dates.
- "Another contract for this vendor and product runs ... – ...: end it first": end or shorten the other contract first.
- "Make a new contract for another vendor or product": vendor and product are fixed on an existing contract.
- "Contract not found": it was removed; refresh the page.
- On a PO, "...: above agreed rate by ...% (contract ₹... per ...): give the reason": the PO rate is above the contract. Give the reason or use the contract rate.
