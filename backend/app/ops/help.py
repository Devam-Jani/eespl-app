# ruff: noqa: E501
"""The "?" on each main page: a short how-to (3 to 6 steps) for the page, and for some pages one
per role. These are the defaults; the office admin edits them in Settings > Help (kept in
help_texts, which win over these). Roles, never names."""

# page (the route) -> role ("" = everyone) -> (title, steps)
DEFAULTS: dict[str, dict[str, tuple[str, list[str]]]] = {
    "/my-work": {"": ("My work", [
        "Everything waiting for you is here, the most urgent first: to-dos from the process rules, approvals, follow-ups.",
        "Open a line to go straight to the page where you act on it.",
        "When you finish the step on that page, the line closes by itself and leaves the list.",
        "Late lines show in red; after the time in the process rules it escalates to the roles the rule names (often the director).",
    ])},
    "/notifications": {"": ("Notifications", [
        "The bell shows what happened on your sites and jobs: new enquiries, approvals, bills, issues.",
        "Click a notification to open what it is about; it is marked read.",
        "Mark all read is in the bell's list at the top; nothing is deleted.",
        "Choose which ones also come by email in My notifications (only when the company has turned email on).",
    ])},
    "/dashboard": {"": ("Dashboard", [
        "Your dashboard shows the numbers for your work: sites, sales, accounts or purchase, by your role.",
        "Pick the period at the top; every tile opens the list behind it.",
        "Red tiles need action; the alerts list explains why.",
    ])},
    "/field": {"": ("My day (check-in)", [
        "Start your day when you leave home: the app records your route while the day is on.",
        "At a site or a client, press Check in and take the selfie; check out when you leave.",
        "Outside the site's radius, give the reason (the distance is shown to your manager).",
        "End the day at home; the km for your travel claim come from the route.",
    ])},
    "/field/claims": {"": ("Travel claims", [
        "Your month's claim is made from your days: km per day times your rate, plus tolls and other bills.",
        "Add a bill (toll, parking) with its photo on the day it belongs to.",
        "Nothing to submit: on the 1st the app sends last month's claim to your manager, who checks it; accounts pay it.",
        "A changed km shows who changed it and why.",
    ])},
    "/petty-cash": {"": ("Petty cash", [
        "Record each site expense with its bill photo: what, how much, for which site.",
        "Your balance shows what you were given and what you spent.",
        "Accounts approve the entries; a rejected one tells you why.",
    ])},
    "/leads": {"": ("Leads", [
        "Every enquiry is a lead: the client, the place, what they need, where it came from.",
        "Log each call or visit on the lead (with photos and GPS on a visit).",
        "Make the quotation from the lead when you know the scope.",
        "Close the lead won or lost with the reason; lost leads count in the closure scorecard.",
    ])},
    "/quotations": {"": ("Quotations", [
        "Start a quotation from a lead or a tender; pick the letterhead and the preset of items.",
        "Prices come from the rate working and the library; a changed rate keeps the reason.",
        "Preview the Word / PDF, then send it; every revision is kept.",
        "Mark it won to start the job (the director assigns the team).",
    ])},
    "/tenders": {"": ("Tenders", [
        "Import the client's BOQ (Excel or PDF) into a tender; check the lines read.",
        "Price the lines: Suggest rates, or the Rate working for systems; accept what is right.",
        "Quote the tender to one or more civil contractors; each gets its own quotation.",
        "Record the outcome: the main contract's winner, our bidders' ranks, won or lost with the reason.",
    ])},
    "/enquiries": {"": ("Enquiries to allocate", [
        "New enquiries without a salesperson wait here.",
        "Pick the salesperson for each (their area and load are shown) and allocate.",
        "The salesperson gets the lead in My work at once.",
    ])},
    "/planning/board": {"": ("Site status board", [
        "Every site's state at a glance: upcoming, running, stuck, finishing.",
        "Pick a site's new column in its \"Move to…\" list (planning, or the site's own engineer), or open it to see why it is stuck.",
        "Each card shows the site's progress and when it was last updated.",
    ])},
    "/sites": {
        "": ("Sites", [
            "Your sites with their progress; open one for its places, stages, team, material and bills.",
            "Use the search and the status filter to find a site.",
            "A site's tabs: Tasks (stages and the quality checklist), Handover, DPR, Material, Finance, Portal.",
        ]),
        "site_engineer": ("Your sites", [
            "Open your site each morning: today's stages, material, labour and the handover dates.",
            "Update the stages in Tasks as work is done; a hold point waits for its inspection.",
            "Sign each finished stage in the quality checklist (Tasks), then the client signs it.",
            "Move a handover date (Handover) with the reason; the client sees it in the portal.",
            "Raise an issue for anything that stops the work (material late, access, drawings).",
        ]),
        "billing": ("Sites for billing", [
            "Open the site, then Measure: the measurement book on site, line by line.",
            "Check the billing checklist: what is measured, approved by the client, and billed.",
            "Make the RA bill from approved lines only; track it to payment on its bill page.",
        ]),
    },
    "/daily-reports": {"": ("Daily reports", [
        "Write the day's report on site: work done per area, labour, material used, hindrances, photos.",
        "Submit it before you leave; the engineer approves it or returns it with a note.",
        "Approved reports feed the progress, the client portal and the material reconciliation.",
    ])},
    "/attendance": {"": ("Attendance", [
        "Mark each worker present, half day or absent for your site today.",
        "A gang check-in (menu: Gang check-in) is a record with its photo; it does not mark attendance here.",
        "Attendance feeds the labour bills and payroll; a change after the day keeps who changed it.",
    ])},
    "/deliveries": {"": ("Deliveries at site", [
        "Material sent to your site waits here until you confirm it.",
        "Count what arrived; enter a shortage or damage with a photo.",
        "Confirm: it goes into the site store; the difference goes back to stores.",
    ])},
    "/snags": {"": ("Snags", [
        "Snags are the client's points to fix, from the portal or from our team.",
        "Assign each snag, fix it, add the photo after, and close it.",
        "The client sees the status in the portal.",
    ])},
    "/issues": {"": ("Issue log", [
        "Raise an issue for anything that stops or risks the work: material, access, quality, payment.",
        "Give it a category, who has it and a due date; add photos and comments as it moves.",
        "Share with the client to make it a portal snag; a late issue escalates to the director.",
        "Resolve it with what was done.",
    ])},
    "/measurements": {"": ("Measurement book", [
        "Pick the site, then Measure: the place, the item (its unit is the work order's) and the sizes.",
        "Sizes in metres or feet and inches; L x B for sqm, the running length for rmt; add deductions and photos.",
        "Send the lines to the client in a set; the client approves or corrects each one.",
        "Accept or dispute each correction; approved lines are locked and only they go into bills.",
    ])},
    "/bills": {"": ("Bills", [
        "Every RA bill with where it is at the client and what is outstanding.",
        "Open a bill: Quantities (billed, certified, the difference with its reason), Steps at the client, Payment.",
        "Mark each step at the client with its date; upload the signed copy at the PM's sign.",
        "Log every payment call; a promised date becomes the next reminder.",
    ])},
    "/billing": {"": ("Client billing", [
        "Contracts, RA bills and invoices per site.",
        "Make an RA bill from the approved measurements; submit it, record the client's certification.",
        "Invoice the certified bill; receipts are matched against the invoice.",
    ])},
    "/billing/checklist": {"": ("Billing checklist", [
        "Pick the site and the tower: flats by area, each cell's state from the zones, handover, stages, book and bills.",
        "Filter by the bill's month to see what that bill took.",
        "Export to Excel for the client's billing team.",
    ])},
    "/work-orders": {"": ("Client work orders", [
        "New work order: pick the won quotation, the client's reference and the client's file (PDF or Excel).",
        "Or copy the lines from our quotation; fill or correct the payment terms with Edit terms.",
        "Compare it with our offer: every deviation (unit, rate, scope, payment ...) is listed.",
        "Accept each deviation or ask the client to amend it (the salesperson gets the to-do).",
        "Accept the work order when none is open: it is locked and its units and rates rule the bills.",
    ])},
    "/guarantees": {"": ("Guarantee register", [
        "Every signed work completion certificate with its guarantee period and areas.",
        "A leakage issue links to the guarantee of its area.",
        "Export the past projects list (PDF or Excel) for pre-qualification.",
    ])},
    "/indents": {"": ("Indents", [
        "Sites ask for material with an indent; approve, change or return each one.",
        "Make the RFQ or the purchase order from approved indents.",
    ])},
    "/purchase-orders": {"": ("Purchase orders", [
        "Make the PO from the indents or the RFQ's chosen quote; check rates against the rate contract.",
        "Send it to the vendor; the GRN at delivery closes the lines.",
        "Freight and other charges go on the PO.",
    ])},
    "/grns": {"": ("Goods receipts (GRN)", [
        "Record what arrived against the PO: quantities, the vendor's bill, photos.",
        "Approve the GRN: the stock goes into the store; a short delivery is noted.",
    ])},
    "/stores": {"": ("Stores & stock", [
        "Each store's stock (godown and sites) at its average rate.",
        "Open a product for its ledger: in, out, transfers, returns.",
        "Transfer material between stores; the site confirms the delivery.",
    ])},
    "/payables": {"": ("Payables", [
        "Vendor bills matched to their GRNs, due by their terms.",
        "Pay a bill and record the payment; part payments are kept.",
    ])},
    "/payroll": {"": ("Payroll & wages", [
        "Monthly payroll from attendance and salary structures.",
        "Check the run, approve it, and export the payslips.",
    ])},
    "/billing/payments": {"": ("Payment follow-up", [
        "Overdue bills, the most overdue first, with the due date from the work order's term.",
        "Log each call: who you spoke to, what they said, the promised date.",
        "Reminders go to accounts at the due date, the salesperson at +5 days and the director at +30.",
    ])},
    "/admin/users": {"": ("Users", [
        "Add people from the Excel template (User import), or one by one here.",
        "Give each person their role(s); site roles also need the person on the site's team.",
        "Copy the one-time link for a new person and send it yourself: they set their own password.",
        "Unlock a person locked after repeated wrong passwords; reset their two-step login if they lost their phone.",
    ])},
    "/admin/audit": {"": ("Audit log", [
        "Every sign-in, export, permission change, deletion and view of someone's route is here.",
        "Filter by kind, person and dates; export to Excel.",
    ])},
}
