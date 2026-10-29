---
page: /consumption
title: Consumption variance
routes: /consumption
mark: ⤓ Excel
---
**Consumption variance** compares, for one site, the material issued to each place with what the treated area done should have used: area done × the system's consumption per sqm, with its wastage. Rows outside the tolerance are flagged. Below is the site average learned from completed areas.

**On the page**
- **Site** (list, top right): the site to check. The first of your sites is chosen when the page opens. The choice is kept in the page address.
- **⤓ Excel**: downloads the site's table as an Excel file ("consumption-variance"), with a flag column.
- The table: **Place**, **Product**, **Sqm done**, **Issued**, **Expected**, **Per sqm**, **Variance**. A flagged row is red with ⚑.
- **Variance** is +n % when more was issued than expected and −n % when less. "not in the system" means the product was issued to the place but is not in the place's system.
- **Site average (completed areas)** (table): per system and product, the **System figure** next to the **Site average** (the median actual consumption per sqm over completed areas) and how many **Areas** it is based on.

**Rules**
- A row is flagged when the variance is outside ± the consumption tolerance (15 % by default, in the site control settings).
- The site average never changes the system's figure by itself. To change it, edit the system in **Systems (rate calculator)**.
- You only see sites you may open.

**What happens next**
- Every week the worker counts the flagged rows of each active site. When there are any, planning and the site engineer get the task "<site>: n material(s) used outside the range on the areas. Review." with a link to this page. If nobody closes it in 3 days, it goes to the director.
- The page has no "reviewed" button: close the task from the notifications once you have looked into it.

**Hands off**
- Receives: material issued to places by the site store; area done from the daily reports.
- Passes on: an over-use to the site engineer (wastage, theft, wrong coats); a system figure that is always off to the estimator.

**When it goes wrong**
- "No treated area with a system on this site yet.": the site's places have no system or no area done yet.
- "Site not found": the site is not one of yours.
- "No completed area with material issued yet.": the site average needs completed areas with material issued.
