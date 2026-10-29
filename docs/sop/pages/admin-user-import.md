---
page: /admin/user-import
title: User import
routes: /admin/user-import
mark: Download the template
---
Everyone for go-live from one Excel file. The app makes the template, checks every row, and
saves nothing while one row has an error. Each new person gets a one-time link to set their own
password. The app sends no email: you copy each link and send it yourself.

**On the page**
- **Download the template**: downloads users-template.xlsx. Sheet **Users** has the columns and one example row; sheet **Roles** lists the role codes; sheet **Sites** lists the codes of the active, planned and on-hold sites.
- **Choose the filled template**: picks your filled .xlsx file. Picking a new file clears the last check.
- **Check the file**: reads every row and lists it. Nothing is saved.
- After the check: "n new", "n already users" and "n with errors" badges. With errors: "Fix the rows below in the file and check it again."
- The check table: **Row**, **Name**, **Email**, **Roles**, **Manager**, **Sites**, **Tracked / travel**, **Check** (the errors in red, or new / already a user).
- **Save n new user(s)**: saves the new people. Greyed until a check has no errors and at least one new person.
- After saving: **Saved: the one-time links (shown once)**. Each new person with their link. "Copy each link and send it to the person. It works once, for 7 days."
- **Copy**: copies that person's link.

**The template's columns**
- **Name**: required.
- **Email**: required; the sign-in name.
- **Phone**: optional.
- **Roles**: one or more role codes or role names from the Roles sheet, separated by commas. The client role cannot be imported.
- **Manager (email)**: optional. An existing user, or a person on a row above.
- **Sites (codes)**: optional. Site codes from the Sites sheet. The person is put on each site's team.
- **Tracked (yes/no)**: field tracking on for the person.
- **Travel eligible (yes/no)**: travel paid per km. Needs a **Rate per km**.
- **Rate per km**: a number from 0 to 100.
- Leave the example row in or delete it: a row starting "(example" is skipped. Empty rows are skipped.

**Rules**
- A person whose email is already a user is left exactly as they are ("already a user"). So running the same file twice adds nobody twice.
- New people are made active, with no password. They cannot sign in until they use their link.
- Their role on each site follows their job: site engineer = in-charge, site supervisor = supervisor, sales = sales, site receiver = receiver, billing / planning / accounts / office admin = office, others = viewer.
- The links are shown once. If you lose one, use **Set-password link** on that person in **Users**.
- The file must be 5 MB or less.

**What happens next**
- Send each link. The person opens it, chooses a password and signs in.
- Check the new people in **Users**: their roles, then their sites on each site's team.
- The import is in the **Audit log** (user.import) with the count of new and existing people.

**Hands off**
- Receives: the list of staff, roles, managers and sites from the director.
- Passes on: each one-time link to its person.

**When it goes wrong**
- "Not an Excel file made from the template": save the file as .xlsx and choose it again.
- "The first row must be the template's headings (Name, Email, ...)": keep the template's first row as it is.
- "No user rows in the file": only the example row or empty rows were found.
- "The file is larger than 5 MB": remove extra sheets or pictures.
- In the **Check** column:
  - "no name", "not an email address", "this email is in the file twice": fix the row.
  - "no role", "no role '<x>' (see the Roles sheet)": use a code from the Roles sheet.
  - "the manager <email> is not a user nor a row above": add the manager first, or move their row above.
  - "no site '<x>' (see the Sites sheet)": use a code from the Sites sheet.
  - "Tracked (yes/no): write yes or no", "Travel eligible (yes/no): write yes or no": write yes or no.
  - "rate per km is not a number", "rate per km out of range", "travel eligible needs a rate per km": fix the rate.
- "n row(s) have errors: nothing saved": fix the file and press **Check the file** again.
- **Copy** does nothing when the app is opened on a plain http address: select the link and copy it by hand.
