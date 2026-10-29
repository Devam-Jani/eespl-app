---
page: /settings/kylas
title: Integrations: Kylas
routes: /settings/kylas
mark: Test connection
---
The link between the app's leads and the Kylas CRM. When it is on, new leads are pushed to Kylas
and their outcomes are read back. The API key is never typed here: it lives only in the server's
.env file, and this page only says whether it is set. Every save is written to the audit log.

**On the page**
- **Test connection**: asks Kylas for its lead sources. The answer shows at the top: "✓ Connected: <n> lead sources", with whether the saved source id is a real Kylas source; or, in red, "✗" and the reason.
- The status box: "Kylas sync is on: new leads are pushed, outcomes are polled." or "Kylas sync is off: <reason>."
- **Lead source id (the "EESPL App" source)**: the Kylas source new leads are pushed under. Empty = push off.
- **Owner rule**: **The Kylas user of whoever entered the lead, else the default owner**, or **Always the default owner**.
- **Default owner (Kylas user id)**: the Kylas user who owns a lead when nobody else fits.
- **Deal pipeline id (optional)**: the Kylas deal pipeline to watch. Empty = deal poll off.
- **Won stage id (optional)**: the stage of that pipeline that means "won". Empty = deal poll off.
- **Lead quotation stage id (optional)**: a lead reaching this Kylas stage gives a "Make quotation" to-do. Empty = off.
- **Custom field for our lead code**, **Custom field for the category**: the Kylas custom fields the app fills.
- **Junk reasons (one per line; a lead closed in Kylas with one of these becomes junk)**: one reason per line.
- **Save**: saves the settings. "Kylas settings saved." shows when it worked.
- **Environment**: **KYLAS_ENABLED** (true or false), **API key** ("set" or "not set") and **Base URL**, read from the server.
- **Leads by Kylas status**: how many leads are in each sync state.

**Rules**
- The sync is on only when KYLAS_ENABLED is true, an API key is in .env and a lead source id is saved here.
- A won stage id needs its deal pipeline id. It is checked live with Kylas when you save.
- The ids come from running "python -m app.cli kylas-discover" on the server.

**What happens next**
- With the sync on, each new lead is pushed to Kylas; leads won, lost or junked in Kylas update the app's leads.

**Hands off**
- Receives: the Kylas ids from whoever runs the server.
- Passes on: leads to the sales team in Kylas, and their outcomes back to the app's Leads page.

**When it goes wrong**
- "Kylas sync is off: KYLAS_ENABLED is false" or "no Kylas API key in .env": the server's .env must be changed; ask whoever runs the server.
- "Kylas sync is off: no Kylas source id in Settings": fill **Lead source id** and press **Save**.
- "✗ No Kylas API key in .env" or "✗ Kylas did not accept the API key": the key is missing or wrong in .env.
- "source <id> is NOT a Kylas lead source": fix **Lead source id**.
- "Set the deal pipeline id together with the won stage id": fill both, or neither.
- "The won stage can only be checked with a Kylas API key in .env": set the key first, or leave **Won stage id (optional)** empty.
- "Could not check the stage with Kylas (HTTP <code>)": Kylas did not answer; try again later.
- "<id> is not a deal pipeline in Kylas" or "<id> is not a stage of pipeline …; its stages are …": pick an id from the list in the message.
