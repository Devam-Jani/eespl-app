---
page: /settings/survey
title: Site survey settings
routes: /settings/survey
mark: Save settings
---
The rules for site surveys: photos, whether camera sizes count for billing, the camera vs laser
check, the AI suggestion from a photo, and the area types with their suggested systems. Every
change is written to the audit log.

**On the page**
- **Every area needs a photo before the survey can be submitted**: when ticked, a survey with an area without a photo cannot be submitted.
- **Camera sizes allowed for billing (off: RA bill quantities from camera-only areas need a laser / manual size or the client's certification)**.
- **Flag camera vs laser differences above (%)**: 0 to 50. An area whose camera and laser sizes differ by more is flagged.
- **AI suggestion from the photo**: "No ANTHROPIC_API_KEY in .env: the Suggest button stays hidden whatever is set here." shows when the server has no key.
- **On (management approval needed)**: switches the AI suggestion on. The **Suggest** button shows in surveys only for roles with the survey AI right.
- **Model**: the AI model name.
- **Monthly cap (₹)**: the most the AI may cost in a month.
- "Spent this month: ₹<n>".
- **Save settings**: saves the settings above. "Saved." shows.

**Area types**
- The table: **Area type** ("to be confirmed by the team" until confirmed), **Suggested system**, **Also suitable (choose)**, **Upturn mm**, **Wastage %**, **Walls**, **Sunk**, **Confirmed**.
- Each change in this table is saved at once, without a button. Number boxes save when you leave them.
- **Suggested system**: the system offered first for this area type.
- **Also suitable (choose)**: other systems offered next to it (hold Ctrl to pick several).
- **Upturn mm**: the default upturn height.
- **Wastage %**: empty uses the system's own wastage.
- **Walls**: the area type includes walls.
- **Sunk**: the area type needs a sunk depth.
- **Confirmed**: tick once the team has agreed the defaults.

**Rules**
- Only roles with the company settings right open this page and save it.
- Changes apply to surveys and estimates made from now on.

**What happens next**
- Sales, site engineers and supervisors doing surveys get the new rules and suggestions. Billing follows the camera-size rule on RA bills.

**Hands off**
- Receives: the survey practice agreed by the director.
- Passes on: the rules surveyors and billing work under.

**When it goes wrong**
- "Missing permission: settings.company": your role may not change these settings.
- A number out of range (for example a difference above 50 %) is refused next to the field.
- "Area type not found": reload the page.
- After an error, the error box stays until you reload, even when a later save works.
