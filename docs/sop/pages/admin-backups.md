---
page: /admin/backups
title: Backups and storage
routes: /admin/backups
---
Whether last night's backup ran, how the server's parts are doing, and how much room the photos,
drawings and PDFs take. The page only shows: there are no buttons. Backups run by themselves on
the server.

**On the page**
- The line under the title: every night the database and the files are saved into one encrypted archive. 14 daily, 8 weekly and 12 monthly copies are kept (the server's settings), and copied off the server when a target is set.
- **The last backup**:
  - **When**: the time of the last backup, marked **good** or **failed**.
  - **Archive**: the archive's name.
  - **Size**: its size.
  - **Kept on the server**: how many archives are kept.
  - **Off-site copy**: where the copy goes, or "not set (BACKUP_REMOTE in .env)".
- **Health**: one badge each for **Database**, **Background worker**, **Road distances (our OSRM)** and **Nightly backup**. Green "ok"; red with the problem ("error", "stale", "never ran", "missed"); grey "not on this copy".
- **Files (photos, drawings, PDFs)**: the total size and number of files, then a row per folder with **Files** and **Size**.

**Rules**
- A backup counts as missed when none succeeded in the last 26 hours.
- **Background worker** is "stale" when it has not ticked for 3 minutes. Reminders, escalations and the nightly jobs wait while it is down.

**What happens next**
- After a night with no good backup, the director and the office admin get the alert "Last night's backup did not run or failed (...). The last good one: ...", linking here. It closes by itself after the next good backup.

**Hands off**
- Receives: the missed-backup alert.
- Passes on: a red badge or a missed backup to whoever runs the server, the same day.

**When it goes wrong**
- "The last backup is missing or failed: <reason>. The director and the office admin have been told.": tell whoever runs the server. Do not wait for a second night.
- "Backups run on the server (the backup container). This copy of the app does not back itself up.": this copy (a test or training copy) has no backups. Nothing to do here.
- **Off-site copy** says "not set": the archives stay only on the server. Ask whoever runs the server to set one before go-live.
