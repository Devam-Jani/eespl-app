---
page: /surveys
title: Site surveys
routes: /surveys, /surveys/:id, /surveys/pilot
mark: New survey
---
The areas measured on site, survey by survey. Each survey belongs to one site, tender or lead. It
lists every area with its size, type and system, adds up the treated area by type and floor,
works out the product quantities, and makes BOQ lines, a draft indent, a PDF and an Excel from
them. You see the surveys of your own sites, tenders and leads (all of them with full access).

**On the list**
- **Survey** column: the survey code (tap it to open the survey) and its title.
- **For**: site, tender or lead, with a link to it. **Date**, **Areas**, **Treated sqm**, **Status** (draft, submitted, approved).
- When you come from a site, tender or lead (for example the to-do "Open the survey"), the list shows only the surveys of that one.
- **Camera pilot**: opens the camera-versus-laser check (see below).
- **⤓ Marker sheet A4 (up to 1.5 m)**: downloads the PDF with two 150 mm markers to print for marker photos.
- **⤓ Marker sheet A3 (up to 2.5 m)**: the same with two 250 mm markers, for areas up to about 2.5 m across.
- **New survey**: opens **New site survey**. {perm: survey.edit}
- **For a**: Site, Tender or Lead. Fixed when you came from a site, tender or lead. {perm: survey.edit}
- **Which**: the site, tender or lead. Only those you may use are accepted. {perm: survey.edit}
- **Title**: a short name, for example "Tower A wet areas". Required. {perm: survey.edit}
- **Start**: creates the survey as a draft dated today, with you as the surveyor, and opens it. {perm: survey.edit}

**On one survey**
- The top shows the code and status, the title, the site / tender / lead, the date and who surveyed it. **Surveys** in the breadcrumb goes back to the list.
- **m** / **ft-in**: the unit you type and read sizes in. It is saved for you, on every survey.
- **Submit**: shown on a draft you can change. Sends the survey for approval; it becomes submitted. {perm: survey.edit}
- **Approve**: shown on a submitted survey. Marks it approved and records you as the approver. {perm: survey.approve}
- **Reopen**: shown on a submitted survey to everyone who opens it. Puts it back to draft.
- **Reopen** is also shown on an approved survey. It puts it back to draft and clears the approval. {perm: survey.approve}
- Tabs: **Areas (n)**, **Products**, **BOQ, indent, PDF**.

**Areas tab**
- Areas are grouped by tower and floor ("No floor" when neither is given).
- Each card shows the first photo (or "no photo"), the name, area type, size, count, the treated area, and a badge: the method, or **camera measured (AR)** / **camera measured (marker)**.
- A red badge **camera vs laser n%** shows when the camera size and the laser / hand size of the same area differ by more than the company limit (3% unless changed in the survey settings).
- **+ Add area**: opens **Add an area**. Shown while the survey can be changed (a draft or submitted survey of yours, never an approved one). {perm: survey.edit}
- **📷 Photo / measure**: opens the camera on this area (see Camera). {perm: survey.edit}
- **Edit**: opens the same form for this area. {perm: survey.edit}
- **Copy**: adds a copy named "(copy)" right away. A camera size is copied as a hand size. {perm: survey.edit}
- **Repeat on floors**: opens **Repeat … on typical floors** with **From floor**, **To floor** (2 and 14 to start) and **Floor name ({n} = the floor number)** ("Floor {n}" to start). {perm: survey.edit}
- **Repeat**: makes one copy per floor with the same size and count, and puts the floor name in the area name. On a site, each copy goes on that tower's floor with the same name, when there is one. The area's own floor is skipped. {perm: survey.edit}
- **✨ Suggest**: shown when the AI suggestion is switched on and the area has a photo. Sends the first photo to the AI, which suggests the area type, the system and condition notes. Each use costs money, within a monthly cap. {perm: survey.ai}
- The **AI suggestion** box shows the confidence and one tick box per part (**Type**, **System**, **Notes**). Sizes are never changed. {perm: survey.ai}
- **Accept ticked**: sets the ticked type and system, and adds the notes to the remarks as "AI: …". {perm: survey.ai}
- **Delete**: asks "Delete <area>?" and removes the area with its photos. {perm: survey.edit}
- The bar at the bottom shows **Treated area … sqm · n areas**. Tap it to see the totals by type and by floor.

**Add an area / Edit (form)**
- **Place on the site**: the floor, flat, toilet, kitchen, balcony, basement or terrace on the site's structure, or **Not on the structure**. Only on a site survey with a structure. This links the area to the work front, which the indent needs. {perm: survey.edit}
- **Tower**, **Floor**: free text. A new area starts with the place, tower and floor of the last one. {perm: survey.edit}
- **Area type**: types marked "(to be confirmed)" are seeded defaults the team has not yet agreed. The type brings its default upturn and wastage, and the **Wall height** or **Sunk depth (mm)** fields. {perm: survey.edit}
- **Name**: left empty, the area is named from the floor and the type. {perm: survey.edit}
- Size tabs: **Length × width**, **Area**, and **Camera outline** on an area measured by the camera. {perm: survey.edit}
- **Size**: type "3.2 x 2.21" in metres or "10'6 x 7'3" in feet-inches. The line under it shows what it read in m and sqm, or "Not readable yet". {perm: survey.edit}
- **Area** (sqm or sqft) and **Perimeter**: for an area you only have as a figure. {perm: survey.edit}
- **Upturn (mm)**: empty means the type's default. **Count**: how many identical areas. {perm: survey.edit}
- **Wall height** (types with walls), **Sunk depth (mm)** (types with a sunk), **Deductions** (sqm or sqft). {perm: survey.edit}
- **System, wastage, method, remarks** (tap to open): {perm: survey.edit}
- **System**: the systems suitable for the area type come first, marked "this client's last choice" or "suggested"; then **All systems**. Left empty, the type's suggested system is used. Your choice is remembered for this client. {perm: survey.edit}
- **Wastage % (this area)**: empty means the type's or the system's. {perm: survey.edit}
- **Measured by**: **Laser meter**, **Tape / by hand**, **Drawing (CAD)**, **Label / client figure**. On an area measured by the camera, **Edit** opens with **Laser meter** chosen: change it if the size really came from the camera, or saving turns the camera size into a laser size. {perm: survey.edit}
- **Remarks**. {perm: survey.edit}
- **Save and add next** (new area only): saves and keeps the form open with the place, tower, floor and type, ready for the next area. {perm: survey.edit}
- **Save**: saves and closes. {perm: survey.edit}

**Camera** (from **📷 Photo / measure**)
- Modes: **Marker photo**, **AR measure** (only on phones that support it; otherwise "AR measure hidden: …" gives the reason), **Laser / hand: proof photo**. {perm: survey.edit}
- The top bar has **✕** (close), the area name and **Torch** / **Torch off** when the phone has a torch. {perm: survey.edit}
- The tilt guide shows "Floor: n° down" (aim 30°–60° down) or "Wall: n° upright". On an iPhone tap **Show the tilt guide** first. Keep the zoom at 1x. {perm: survey.edit}
- Marker photo: lay both printed sheets flat in the area. Wait for "2 markers found", then press the round shutter. Tap the corners of the area in order on the photo; the sides and the area show as you tap. {perm: survey.edit}
- **Undo corner** removes the last tap, **Retake** starts again, **Save measurement** saves the photo with the drawn outline and the camera size. {perm: survey.edit}
- AR measure: **Start AR**, tap the corners on the floor, then **Done** (or **Cancel**). For a wall type, measure the wall height or type it and press **Use**. The plan drawing and the camera size are saved. {perm: survey.edit}
- Proof photo: take the photo, then **Save photo** or **Retake**. The size stays the laser / hand reading typed in the area. {perm: survey.edit}

**Products tab**
- **Whole survey**: each product with its quantity and the whole packs to order (with the spare left over). Packs are rounded only on this total.
- **By floor**: the quantities per floor, not rounded to packs.
- A yellow note lists the areas that have no system yet; they are not counted.

**BOQ, indent, PDF tab**
- **Tender BOQ**: the tender field, left empty, uses this survey's tender (or the lead's or site's tender). For a survey with no tender, type the **Tender id**. {perm: tender.edit}
- **Split by area type**: one line per system and area type, instead of one per system. {perm: tender.edit}
- **Create BOQ lines**: adds one line per system with the summed treated sqm to the tender, priced by the tender's Suggest. Each line remembers its areas. The message reads "n BOQ line(s) added to <tender>; m priced by Suggest." {perm: tender.edit}
- **Material indent**: each floor shows "ready / areas". Only floors with a place ticked "work front ready" by the supervisor are listed. {perm: indent.create}
- **Show not ready (planning: order ahead)**: lists every floor and orders the areas that are not ready too. {perm: indent.create}
- Tick the floors you want, or none for all of them. {perm: indent.create}
- **Create indent draft (n floors)** / **Create indent draft (all floors)**: makes a draft indent for the site with the product totals in whole packs, remark "From survey <code> (<floors>)". The message gives its code. Open it under Indents to check and send it. {perm: indent.create}
- **Include rates**: adds the rates to the PDF. {perm: tender.margin}
- **⤓ Survey PDF**: downloads the survey report.
- **⤓ Excel**: downloads the areas as a spreadsheet.

**Camera pilot**
- Every area measured both by the camera and by laser / hand: the camera sqm, the laser sqm and the difference. Rows above the limit are highlighted.
- The tiles show, for **AR measure** and **Marker photo**, the number of areas, the average and the worst difference.
- **⤓ Excel**: downloads the same table with a summary sheet.
- Measure 10 rooms both ways before trusting the camera.

**Rules**
- Only a draft or submitted survey can be changed. An approved survey is locked until it is reopened.
- A survey needs at least one area to be submitted. When the company setting "Every area needs a photo" is on, every area needs a photo too.
- Treated area = (floor area − deductions + perimeter × upturn + perimeter × wall height + perimeter × sunk depth) × count. Wall height and sunk depth count only for area types that use them.
- A camera size is kept as the camera value. It becomes the area's size only while the area has no laser, hand or drawing size. When both exist, the laser / hand size is used and the difference is checked.
- Billing from camera-only sizes follows the company setting "Camera sizes allowed for billing". When it is off, RA bill quantities from such areas need a laser / hand size or the client's certification.
- Areas with no system (and no suggested system on their type) are left out of products, BOQ lines and indents.
- The indent orders only areas on a place marked "work front ready", unless **Show not ready (planning: order ahead)** is ticked. {perm: indent.create}
- Rates appear in the PDF only for roles allowed to see margins. {perm: tender.margin}

**What happens next**
- **Submit** on a site survey closes the site engineer's to-do "get the AutoCAD drawing from the client and finish the site survey". No one is notified to approve it: tell the approver.
- **Approve** and **Reopen** send no notification.
- BOQ lines appear on the tender for the estimator to check and price. {perm: tender.edit}
- The draft indent waits under Indents to be checked and sent for approval. {perm: indent.create}

**Hands off**
- Receives: the to-do "finish the site survey" when the director assigns the site engineer to a won job; the client's AutoCAD drawing; "work front ready" ticks from the site supervisor.
- Passes on: the submitted survey to the director or office admin for approval; BOQ lines to the estimator on the tender; a draft indent to store and purchase.

**When it goes wrong**
- "You cannot change this survey": it is not one of your sites, tenders or leads. Ask the site engineer of that site, or your manager.
- "<code> is approved: reopen it to change it": an approver must press **Reopen** first.
- "Add at least one area": add an area before **Submit**.
- "Every area needs a photo first: …": take a photo (or a proof photo) on each area listed.
- "<code> is <status>; submit it first": only a submitted survey can be approved.
- "<code> is a draft": a draft does not need reopening.
- "Site not found" / "Tender not found" / "Lead not found" on **Start**: you may only start a survey on your own site, tender or lead.
- "Give the length and the width" or "Give the area": fill the size before saving.
- "Type the size as length x width, e.g. 3.2 x 2.21" (or "e.g. 10'6 x 7'3" in ft-in): the size could not be read. Put "x" between length and width.
- "That place is not on this survey's site": choose the place from the list again.
- "Give a floor range of at most 100 floors": **To floor** must not be below **From floor**, and at most 100 floors apart.
- "Too dark: turn the torch on or move to the light, then take it again." or "Blurred: hold the phone still (lean on something) and take it again.": the photo was refused; take it again.
- "No marker found: lay both sheets flat and keep them fully in the photo." or "Only one marker found: both sheets must be in the photo.": both printed markers must be fully in the picture.
- "Move closer: a marker is only n% of the photo width (needs 10%).": step closer, or use the A3 sheet.
- "The two markers disagree on scale by n% (more than 2%): flatten the sheets and take the photo again."
- "Markers from both sheet sizes are in the photo: use one pair only (A4 or A3)."
- "Too big for one marker photo: use AR or the laser.": the area is wider than the markers can measure; **Save measurement** stays greyed.
- "The camera did not start: … Allow camera access for this site.": allow the camera in the browser settings and open the camera again.
- "AR stopped: …": AR lost tracking or was closed; start again, or use the marker photo or the laser.
- "The AI service did not answer; try again later": the suggestion failed (or the monthly cap is reached); choose the type and system yourself.
- "Choose the tender for the BOQ lines": the survey has no tender; type the tender id.
- "Missing permission: tender.edit": you cannot change that tender.
- "No area has a system yet": choose a system on the areas (or a suggested system on their area type) first.
- "No work front is ready on those floors: …": the supervisor must tick "work front ready" on site, or tick **Show not ready (planning: order ahead)** to order ahead.
- "No product quantities on those floors (pick systems first)": the chosen floors have no system set.
- "Choose the site for the indent": the survey has no site; an indent needs one.
- "Missing permission: indent.create on that site": you can make indents only for your own sites.
