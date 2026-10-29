---
page: /settings/quotation-library
title: Quotation library
routes: /settings/quotation-library
mark: + New
---
The text and rates quotations are built from: presets, offer items, specifications, offer lines,
letters, letterheads and references, plus the quotation settings. Every change keeps a version
that can be restored; quotations already made keep their own copy. Every change is written to the
audit log.

**On the page**
- **Presets**, **Offer items**, **Specifications**, **Offer lines**, **Letters**, **Letterheads**, **References**, **Settings** (tabs). The page opens on **Offer items**.
- **Search** (field): filters the list of the open tab.
- **To check**: shows only rows marked **imported, check**.
- **+ New**: opens an empty form for the open tab.
- **Add from completed sites** (References tab): makes a reference for every completed site that has none yet (client, project, works done, area in sqft). They come in marked **imported, check**. The message says how many were added.
- A row in the list: its title and version (for example "v3"). Badges: **imported, check** (needs a look after an import), **area type missing**, and **<n> check(s)** on an offer item whose specification and budget do not agree (point at it to read them).
- Click a row: opens its form, a **Preview** of how it prints, and its **Version history**.

**The form, every tab**
- **Mark checked**: shown on a row marked **imported, check**. It clears the mark in the form; press **Save (new version)** to keep it.
- **Create** (new row) or **Save (new version)** (existing row): saves. "Saved as version <n>" shows.
- **Active**: shown on an existing row. Untick it to stop it being offered in new quotations.
- **Version history**: each version, what was done, by whom and when. **Restore** (on an older version) asks "Restore version <n>? It becomes a new version; nothing is lost." and brings back that version as a new one.

**Presets**
- **Name**, **Letterhead**, **Letter template** ("The letterhead's" by default), **T&C template id (empty: the letterhead's)**.
- **Include "Our esteemed clients"**: adds the references page.
- **Areas, in order**: the offer items the preset puts in a quotation. **↑**, **↓** move one; **Remove** takes it out; **+ Add an area…** adds one.

**Offer items**
- **Name**, **Budgetary offer title**, **Area type**, **Order**.
- **Specification blocks (options)**: the specifications printed for this area. **Remove** takes one out; **+ Add a specification block…** adds one.
- **Offer lines**: the budget lines for this area. **Opt.** gives a line an option number. **Remove** takes one out; **+ Add an offer line…** adds one.
- "Specification and budgetary offer do not agree (warnings, not blocks)": a list of mismatches. You can still save.

**Specifications**
- **Title (prints in capitals)**, **Heading prefix**, **Option (empty: always)**, **Area type**.
- Each stage section: **Stage (e.g. Surface preparation)**, **Option** (an option number makes the section an alternative), **↑**, **↓**, **Remove**.
- Each step: its text, **Client's scope**, **If required**, **✕** to remove it; **+ Step** adds one.
- **+ Stage section**: adds a section.
- **Caption** and **Choose the image**: adds a picture to the specification (saved at once as a new version).

**Offer lines**
- **Description**, **UoM**, **Rate from** (**Fixed rate**, **System build-up** or **Rate library**), **Default rate (₹)**, and **System id** or **Rate library item id** for those choices.
- **If required**, **Client's scope (prints in the rate column)**.

**Letters**
- **Name**, **Opening**, **Subject**, **Body**, **Enclosures (one per line)**. Text in {braces} is a placeholder filled from the quotation. Unknown {placeholders} are refused on save.

**Letterheads**
- **Name**, **Company name**, **Signatory firm line (For … PVT. LTD.)**, **Brand ({brand})**, **Default signatory**, **Designation (printed under the name)**, **Second signatory (optional)**, **Second signatory's designation**.
- **Signs the certificates (work completion, guarantee)**: **The default signatory** or **The second signatory**.
- **Colour**, **Accent colour**, **References from state**, **Letter template**, **Header text**, **Footer text**.
- **Pre-printed paper: leave the header and footer space blank (for printing on letterhead stationery)**.
- **Logo**, **Header band (full width)**, **Footer band (full width)**, **Watermark (made faint)**: shown once the letterhead is saved. **Choose the image** uploads it at once as a new version.

**References**
- **Client**, **Project**, **Application method & area**, **State**, **Area covered**, **Unit (SQFT, SQMT, RMT)**, **Order**, **Include in new quotations**.

**Settings tab**
- **Validity (days, default)**, **Follow-up days after sending** (for example "3, 7, 15"), **Closure target (%), everyone**, **Default letterhead**.
- **Closure target per salesperson**: one box per salesperson; empty uses the company target.
- **Save settings**: saves; "Saved." shows.
- **Word template**: says whether the built-in or an uploaded template is used. **⤓ Template** downloads it. **Upload a Word template** uploads a restyled .docx; "The new Word template is used for every quotation from now on." **Back to the built-in one** (shown after an upload) goes back.

**Rules**
- Only roles with the quotation template right open this page and change it.
- Required to create: a letterhead needs a name, company name and signatory firm line; a letter a name, subject and body; a specification a title; an offer line a description and UoM; an offer item a name and budgetary offer title; a reference a client and project; a preset a name.
- Follow-up days run from 1 to 365.
- Quotations already made never change when the library changes.

**What happens next**
- Sales and estimators build new quotations from the presets and items. Follow-up to-dos go to the salesperson on the follow-up days after a quotation is sent.

**Hands off**
- Receives: specification text, rates and references from estimators and the director.
- Passes on: the building blocks sales and estimators use for quotations.

**When it goes wrong**
- "Fill in: <fields>": fill those fields and press **Create** again.
- "Unknown placeholder(s): {…}. Allowed: {…}": use only the placeholders in the list.
- "Unknown or repeated specification block" or "Unknown offer line": a block or line was removed or added twice. Remove it and add it again.
- "Follow-up days run from 1 to 365": correct the follow-up days.
- "That is not a Word .docx file": upload the template saved as .docx from Word.
- On the **Settings** tab an error shows in the same green box as "Saved."; read the text.
