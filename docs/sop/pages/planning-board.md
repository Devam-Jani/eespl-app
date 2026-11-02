---
page: /planning/board
title: Site status board
routes: /planning/board, /assignments/:id
mark: ⤓ Allocation list (PDF)
---
Every open site in three columns: **Upcoming**, **Ongoing** and **Completed, to bill**. Each card
shows who runs the site and when it was last updated. Planning sees every site. Other roles see
only the sites their site access allows.

**On the page**
- Each column heading shows the column name and a count of its sites. An empty column says "None."
- A site card shows the site code and name (a link to the site), then **Sales**, **Engineer** and **Supervisor** (the site's members), then "n% done · updated <date>".
- "Updated" is the latest of: the last board move, the last daily report change, the last task change.
- **Move to…** (list on a card): moves the site to another column. The page reloads with the site in its new column. Shown only to planning and to the site's own engineer.
- **⤓ Allocation list (PDF)**: downloads the site allocation list as a PDF (A4 landscape). One row per site on the board: Status, Site, Name, Salesperson, Site engineer, Supervisor, Last update. Also shown to the list's recipients when they come from its notification. {perm: planning.view}
- **⤓ Excel**: the same list as an Excel file. {perm: planning.view}
- **Send to recipients**: sends the allocation list to the people chosen in the team settings, as an in-app notification. Nothing is emailed. The page says "Sent to n person(s) in the app." {perm: planning.edit}
- **Not on the board** (yellow note and section): planned or active sites that are in no column yet. Each has its own card with **Move to…**. Place them in a column.

**Rules**
- Planning moves any site. A site engineer (or another role allowed to post updates on that site) moves only their own sites, usually from the phone.
- The **Move to…** list shows only on the cards you may move.
- Closed sites and DEMO sites are never on the board.
- A completed or on-hold site that was never placed in a column does not appear anywhere on the board.
- A won job that is assigned goes on the board as **Upcoming** by itself (see "Won job" below).
- Every move is written to the audit log with the old and the new column.

**What happens next**
- The recipients of **Send to recipients** get a notification "Site allocation list of <date>". It opens this board and downloads the list (PDF). {perm: planning.edit}
- The time of the last send is kept in the team settings. {perm: planning.edit}

**Hands off**
- Receives: new upcoming sites from the director's team assignment; column moves from site engineers.
- Passes on: the allocation list to the chosen recipients. {perm: planning.edit}

**When it goes wrong**
- "Only planning or the site's engineer moves it": you tried to move a site that is not yours. Ask planning or the site's engineer.
- "Unknown column": the column was not one of the three. Reload the page and try again.
- "Site not found": the site was deleted or is not visible to you. Reload the page.
- "Choose who receives the allocation list (settings)": no recipients are set. Pick them in the team settings first, then send again. {perm: planning.edit}

### Won job: assign the team (/assignments/:id)

Opened from the "Won: <title>. Assign the salesperson and the site engineer." to-do, or from My
work. It decides who handles a won quotation or tender.

**On the page**
- **Won: <title>**: the job. Below it: the day it was won, and the site when one is already linked.
- **Salesperson** (field): the people holding the sales role. It starts at the quotation's salesperson or the tender owner.
- **Site engineer** (field): the people holding the site engineer role, with their job title.
- **Assign**: saves the choice. It stays grey until both fields are chosen. The app then opens the site. {perm: jobs.assign}
- Without the right to assign, the page says "The director decides (or planning, when the director allows it)." and has no button.
- Once decided, the page shows who was chosen, who decided and when, and whether the first site visit is logged yet.

**Rules**
- Only the director decides, or a person the director has given the right to assign won jobs. {perm: jobs.assign}
- One decision per job. It cannot be changed from this page afterwards.
- One job per tender: a second win on the same tender does not make a second job.

**What happens next**
- The site is linked: the tender's site if there is one, else a new site is made in **Planned** status with its own site store.
- The site engineer becomes the site in-charge and a member as "incharge". The salesperson becomes a member as "sales".
- The site goes on the status board as **Upcoming**, unless it is already in a column.
- The tender owner and the quotation's salesperson become the chosen salesperson.
- The salesperson is told: "<site>: make the first site visit." (action **Log the visit**). It closes when the visit is logged.
- The site engineer is told: "<site>: get the AutoCAD drawing from the client and finish the site survey." (action **Open the survey**). It closes when the survey is done.
- Planning is told the site was added as upcoming on the status board.
- If nobody acts within 3 days, planning is reminded.

**Hands off**
- Receives: the won quotation or tender from sales or the estimator. An undecided job is raised again to the director after 24 hours and to the office admin after 48 hours.
- Passes on: the first visit to the salesperson, the drawing and survey to the site engineer, the upcoming site to planning.

**When it goes wrong**
- "The director decides who handles a won job": you do not have the right to assign. Ask the director.
- "Already decided": someone assigned this job already. Reload the page to see who.
- "Unknown user": a chosen person no longer exists. Reload and pick again.
- "Not found": the job does not exist. Open it again from My work.
