---
page: /settings/company
title: Company profile
routes: /settings/company
mark: Save
---
The company's own details: legal name, tax numbers, contact details, the default GST and the
pricing defaults, and the logo printed on documents. There is one profile for the whole company.
Every change is written to the audit log.

**On the page**
- **Legal name**, **Trade name**: the company names printed on documents. Up to 200 characters.
- **PAN** (field): 10 characters, like the grey example. Spaces are removed and letters made capital.
- **TAN** (field): 10 characters (4 letters, 5 digits, 1 letter).
- **CIN** (field): the 21-character company number.
- **TDS %** (field): the company's TDS rate.
- **Default GST %** (field): the GST rate the tender pricing uses when nothing else is set (18 when no profile exists).
- **Auto-pricing threshold (0–1)** (field): when the app suggests BOQ rates, a suggestion that scores below this number stays unpriced for the estimator to fill in. 0.55 is the usual value.
- **Email**, **Phone**, **Website**: the company's contact details for documents.
- **Suggested rate from the library** (field): how the app picks the suggested rate from past BOQs: **Same channel's median, else the median**, **Median of all BOQs**, **Same channel's last rate, else the median**, **Lower of latest and median**, **Latest rate** or **Trimmed mean (top and bottom 10% dropped)**.
- **Save**: saves the form. "Company profile saved." shows when it worked.
- **Logo**: the current logo, or "No logo yet."
- **Choose the logo**: pick a PNG, JPEG or WebP image of up to 2 MB. It is uploaded at once and replaces the old logo. "Logo uploaded." shows when it worked.
- **Remove logo**: shown when there is a logo. Asks "Remove the logo?" and then deletes it.

**Rules**
- Only roles with the company settings right open this page and change it.
- Leaving **Default GST %**, **Auto-pricing threshold (0–1)** or the rate choice empty keeps the old value; it does not clear it.
- Other empty fields are saved as empty.
- Every user may see the logo, because it goes on documents.

**What happens next**
- The names, tax numbers, contact details and logo go on the documents the app prints from now on.
- The GST, threshold and rate choice apply to the next pricing run on a tender BOQ. Prices already set stay.

**Hands off**
- Receives: the company's registration details from the directors or accounts.
- Passes on: the details printed on bills, POs and quotations made by every role.

**When it goes wrong**
- "PAN must look like AAPFU0939F (10 characters)": the PAN has the wrong shape. Type the 10 characters again.
- "must look like AHMA12345B" (TAN) or "must look like U74999GJ2019PTC123456" (CIN): the number has the wrong shape.
- A wrong email or a threshold above 1 is shown next to the field: correct it and press **Save** again.
- "The logo must be a PNG, JPEG or WebP image": save the logo in one of these formats.
- "The logo must be 2 MB or smaller": make the image smaller first.
- "The file content is not a valid image of that type": the file is damaged or renamed. Save it again from an image program.
