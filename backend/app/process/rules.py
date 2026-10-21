# ruff: noqa: E501  (rule texts read better unwrapped)
"""The process chain Mr. Sunil described in the 9 Oct meeting (enquiry to payment): one rule per
step. Each rule turns an event into notifications: who is told (by role, resolved from the
event's site), the message and the one-tap action, which events close it, and the escalation
(after how many hours, to whom). All of it is editable in Settings > Process rules; these are the
seeds.

Recipient roles: salesperson, site_engineer, supervisor (the site's people), planning, billing,
accounts, store_purchase, estimator (the site's member holding the role, else the role's default
user), director, office_admin (everyone holding the role), author (who made the record).

Message fields come from the event's data ({site}, {area}, {qty} ...); {amount} is shown only to
roles that may see amounts, {cost} only to roles that may see costs. The places an event is about
(data "places": [{place, qty, unit}]) go one per line under the message, never joined into it.

"short" and "ref" make the email subject, at most 80 characters:
"[EESPL] <short> · <site code> <ref>", e.g. "[EESPL] Work done, make the bill · S-2026-0001
Block A raft"; the full message stays in the body.
"""

H = 1  # hours
D = 24  # a day in hours

DEFAULT_RULES: list[dict] = [
    {
        "code": "enquiry_unassigned", "number": 1, "event": "enquiry_unassigned",
        "short": "Allocate a salesperson", "ref": "{lead} {name}",
        "title": "Enquiry entered without a salesperson",
        "recipients": [{"role": "planning", "message": "Enquiry {lead}: {name}, {city}. Allocate a salesperson.", "action": "Allocate"}],
        "link": "/enquiries?lead={lead_id}", "closed_by": ["lead_allocated"],
        "escalations": [{"after_hours": 24 * H, "to": ["director"]}],
    },
    {
        "code": "lead_allocated", "number": 2, "event": "lead_allocated",
        "short": "Enquiry allocated to you", "ref": "{lead} {name}",
        "title": "Salesperson allocated",
        "recipients": [{"role": "salesperson", "message": "Enquiry {lead} allocated to you: {name}, {city}, {phone}. {requirement}. Prepare the quotation.", "action": "Prepare quotation"}],
        "link": "/leads/{lead_id}", "closed_by": ["quotation_created"],
        "escalations": [{"after_hours": 3 * D, "to": ["planning"]}],
    },
    {
        "code": "send_blocked", "number": 3, "event": "send_blocked",
        "short": "Cannot be sent yet", "ref": "{what}",
        "title": "Quotation or tender BOQ blocked by the send checklist",
        "recipients": [{"role": "author", "message": "{what} cannot be sent yet: {missing}", "action": "Fix"}],
        "link": "{link}", "closed_by": ["quotation_sent", "tender_submitted"], "escalations": [],
    },
    {
        "code": "quotation_sent", "number": 4, "event": "quotation_sent",
        "short": "Quotation sent", "ref": "{quotation}",
        "title": "Quotation sent: follow-ups on the schedule",
        "recipients": [{"role": "salesperson", "message": "{quotation} sent to {client}: follow-ups on day 2, 7, 15 and 30.", "info": True}],
        "link": "/quotations/{quotation_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "followup_due", "number": 4.1, "event": "followup_due",
        "short": "Follow up the quotation", "ref": "{quotation}",
        "title": "Quotation follow-up due (the schedule of rule 4)",
        "recipients": [{"role": "salesperson", "message": "Follow up {quotation} with {client} (day {day} after sending).", "action": "Follow up"}],
        "link": "/quotations/{quotation_id}", "closed_by": ["followup_done"],
        "escalations": [{"after_hours": 2 * D, "to": ["planning"]}],
    },
    {
        "code": "negotiation_logged", "number": 5, "event": "negotiation_logged",
        "short": "Rate change asked", "ref": "{what}",
        "title": "Negotiation logged: the client asks for a rate change",
        "recipients": [
            {"role": "estimator", "message": "{what}: the client asked \"{asked}\". Revise the offer.", "action": "Revise the offer"},
            {"role": "salesperson", "message": "{what}: the client asked \"{asked}\". Revise the offer.", "action": "Revise the offer"},
        ],
        "link": "{link}", "closed_by": ["quotation_revised", "tender_submitted"],
        "escalations": [{"after_hours": 2 * D, "to": ["director"]}],
    },
    {
        "code": "tender_submitted", "number": 6, "event": "tender_submitted",
        "short": "Tender submitted", "ref": "{tender}",
        "title": "Tender submitted: awaiting award",
        "recipients": [
            {"role": "salesperson", "message": "Tender {tender} submitted: awaiting award; a follow-up every 60 days until won or lost.", "info": True},
            {"role": "planning", "message": "Tender {tender} submitted: awaiting award.", "info": True},
        ],
        "link": "/tenders/{tender_id}?tab=award", "closed_by": [], "escalations": [],
    },
    {
        "code": "job_won", "number": 7, "event": "job_won",
        "short": "Won, assign the team", "ref": "{title}",
        "title": "Quotation or tender won",
        "recipients": [{"role": "director", "message": "Won: {title}. Assign the salesperson and the site engineer.", "action": "Assign"}],
        "link": "/assignments/{assignment_id}", "closed_by": ["job_assigned"],
        "escalations": [{"after_hours": 24 * H, "to": ["director"]}, {"after_hours": 48 * H, "to": ["office_admin"]}],
    },
    {
        "code": "job_assigned", "number": 8, "event": "job_assigned",
        "short": "Team assigned", "ref": "",
        "title": "Team assigned",
        "recipients": [
            {"role": "salesperson", "message": "{site}: make the first site visit.", "action": "Log the visit", "link": "/sites/{site_id}?visit=1", "closed_by": ["site_visit_logged"]},
            {"role": "site_engineer", "message": "{site}: get the AutoCAD drawing from the client and finish the site survey.", "action": "Open the survey", "link": "/surveys?site={site_id}", "closed_by": ["survey_done"]},
            {"role": "planning", "message": "{site} added as upcoming on the status board.", "info": True},
        ],
        "link": "/sites/{site_id}", "closed_by": [],
        "escalations": [{"after_hours": 3 * D, "to": ["planning"]}],
    },
    {
        "code": "front_ready", "number": 9, "event": "front_ready",
        "short": "Front ready, plan material", "ref": "{area}",
        "title": "Work front ready",
        "recipients": [{"role": "planning", "message": "{site}: {area} ready ({qty} {unit}). Material plan for this area (wastage {wastage}).", "action": "Plan material"}],
        "link": "/sites/{site_id}/material-plan?node={node_id}", "closed_by": ["indent_created"],
        "escalations": [{"after_hours": 24 * H, "to": ["director"]}],
    },
    {
        "code": "indent_approved", "number": 10, "event": "indent_approved",
        "short": "Indent approved, place the PO", "ref": "{indent}",
        "title": "Indent approved",
        "recipients": [{"role": "store_purchase", "message": "Indent {indent} for {site} approved: place the PO at the contract rate.", "action": "Place the PO"}],
        "link": "/indents/{indent_id}", "closed_by": ["po_created"],
        "escalations": [{"after_hours": 24 * H, "to": ["planning"]}],
    },
    {
        "code": "dn_created", "number": 11, "event": "dn_created",
        "short": "Material on the way", "ref": "{dn}",
        "title": "PO sent and delivery note made",
        "recipients": [
            {"role": "site_engineer", "message": "Material on the way to {site}: {items}, expected {expected}. Prepare the surface (cleaning, grinding) before it arrives.", "info": True},
            {"role": "supervisor", "message": "Material on the way to {site}: {items}, expected {expected}. Prepare the surface (cleaning, grinding) before it arrives.", "info": True},
        ],
        "link": "/deliveries/{dn_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "delivery_confirmed", "number": 12, "event": "delivery_confirmed",
        "short": "Delivery confirmed", "ref": "{dn}",
        "title": "Delivery confirmed at site",
        "recipients": [
            {"role": "site_engineer", "message": "{dn}: material at {site}, work can start on this area.", "info": True},
            {"role": "planning", "message": "{dn}: material at {site}, work can start on this area.", "info": True},
        ],
        "link": "/deliveries/{dn_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "first_dpr_on_area", "number": 13, "event": "first_dpr_on_area",
        "short": "Work started", "ref": "{area}",
        "title": "First daily report on an area",
        "recipients": [{"role": "planning", "message": "{site}: work started on {area}; the site is now ongoing on the status board.", "info": True}],
        "link": "/planning/board", "closed_by": [], "escalations": [],
    },
    {
        "code": "dpr_submitted", "number": 14, "event": "dpr_submitted",
        "short": "Daily report to approve", "ref": "{date}",
        "title": "Daily report submitted",
        "recipients": [{"role": "site_engineer", "message": "Daily report of {date} for {site}: approve or return.", "action": "Approve or return"}],
        "link": "/sites/{site_id}?tab=dpr&day={day}", "closed_by": ["dpr_reviewed"],
        "escalations": [{"after_hours": 24 * H, "to": ["planning"]}],
    },
    {
        "code": "dpr_new_area", "number": 15, "event": "dpr_new_area",
        "short": "Area not in the quotation", "ref": "{area}",
        "title": "Area in a daily report that is not in the quotation",
        "recipients": [
            {"role": "planning", "message": "{site}: work on {area}, which is not in the quotation. Quote or approve this area.", "action": "Quote or approve"},
            {"role": "salesperson", "message": "{site}: work on {area}, which is not in the quotation. Quote or approve this area.", "action": "Quote or approve"},
        ],
        "link": "/new-areas", "closed_by": ["new_area_decided"],
        "escalations": [{"after_hours": 48 * H, "to": ["director"]}],
    },
    {
        "code": "stage_done", "number": 16, "event": "stage_done",
        "short": "Work done, make the bill", "ref": "{area}",
        "title": "Stage done: make the stage bill",
        "recipients": [
            {"role": "billing", "message": "Work done on {date}: make the stage bill (measurement book entry attached).", "action": "Start bill"},
            {"role": "salesperson", "message": "Work done on {date}: billing makes the stage bill.", "info": True},
        ],
        "link": "/ready-to-bill?item={ready_id}", "closed_by": ["stage_billed"],
        "escalations": [{"after_hours": 7 * D, "to": ["director"]}],
    },
    {
        "code": "monthly_ra_due", "number": 17, "event": "monthly_ra_due",
        "short": "Monthly RA bill due", "ref": "",
        "title": "Monthly cycle day: RA bill to raise",
        "recipients": [{"role": "billing", "message": "{site}: the monthly RA bill is due (measured work not billed).", "action": "Raise RA bill"}],
        "link": "/sites/{site_id}?tab=finance", "closed_by": ["site_billed"],
        "escalations": [{"after_hours": 5 * D, "to": ["director"]}],
    },
    {
        "code": "bill_sent", "number": 18, "event": "bill_sent",
        "short": "Bill sent, follow up", "ref": "{bill}",
        "title": "Bill sent to the client",
        "recipients": [
            {"role": "salesperson", "message": "{bill} for {site} sent to the client: follow up for certification.", "action": "Follow up"},
            {"role": "accounts", "message": "{bill} for {site} sent: receipt expected ({amount}).", "info": True},
        ],
        "link": "/bill-tracking?site={site_id}", "closed_by": ["bill_certified"],
        "escalations": [{"after_hours": 15 * D, "to": ["salesperson"]}],
    },
    {
        "code": "cert_differs", "number": 19, "event": "cert_differs",
        "short": "Certified less than billed", "ref": "{bill}",
        "title": "Client certified less than billed",
        "recipients": [
            {"role": "billing", "message": "{bill} for {site}: the client certified {certified} against {billed} billed. Give the reason.", "action": "Give the reason"},
            {"role": "salesperson", "message": "{bill} for {site}: the client certified {certified} against {billed} billed. Give the reason.", "action": "Give the reason"},
        ],
        "link": "/bill-tracking?site={site_id}", "closed_by": ["diff_reason_given"],
        "escalations": [{"after_hours": 3 * D, "to": ["director"]}],
    },
    {
        "code": "payment_received", "number": 20, "event": "payment_received",
        "short": "Payment received", "ref": "{client}",
        "title": "Payment received",
        "recipients": [
            {"role": "salesperson", "message": "Payment received from {client} for {site}: {amount}.", "info": True},
            {"role": "director", "message": "Payment received from {client} for {site}: {amount}.", "info": True},
        ],
        "link": "/receivables", "closed_by": [], "escalations": [],
    },
    {
        "code": "labour_bill_entered", "number": 21, "event": "labour_bill_entered",
        "short": "Labour bill to check", "ref": "{bill}",
        "title": "Labour bill entered",
        "recipients": [
            {"role": "billing", "message": "Labour bill {bill} of {contractor} for {site}: check it against the work done ({check}).", "action": "Check"},
            {"role": "director", "when": "flagged", "message": "Labour bill {bill} of {contractor} for {site}: productivity low ({check}). Decide.", "action": "Decide", "link": "/payables?tab=subcon", "closed_by": ["labour_decided"]},
        ],
        "link": "/labour-check", "closed_by": ["labour_checked"], "escalations": [],
    },
    {
        "code": "consumption_high", "number": 22, "event": "consumption_high",
        "short": "Consumption off the range", "ref": "",
        "title": "Consumption above the learned range on an area",
        "recipients": [
            {"role": "planning", "message": "{site}: {flags} material(s) used outside the range on the areas. Review.", "action": "Review"},
            {"role": "site_engineer", "message": "{site}: {flags} material(s) used outside the range on the areas. Review.", "action": "Review"},
        ],
        "link": "/consumption?site={site_id}", "closed_by": ["consumption_reviewed"],
        "escalations": [{"after_hours": 3 * D, "to": ["director"]}],
    },
    {
        "code": "last_stage_done", "number": 23, "event": "last_stage_done",
        "short": "Last stage done, final bill", "ref": "",
        "title": "Last stage of the site done",
        "recipients": [
            {"role": "billing", "message": "{site}: the last stage is done. Make the final bill.", "action": "Final bill"},
            {"role": "planning", "message": "{site}: all work done; moved to completed, to bill.", "info": True},
        ],
        "link": "/sites/{site_id}?tab=finance", "closed_by": ["site_billed"],
        "escalations": [{"after_hours": 7 * D, "to": ["director"]}],
    },
    {
        "code": "kylas_quotation", "number": 24, "event": "kylas_quotation",
        "short": "Make the quotation", "ref": "{lead} {name}",
        "title": "Kylas lead at the quotation stage",
        "recipients": [{"role": "salesperson", "message": "Kylas: {lead} {name} is at the quotation stage. Make the quotation (pick the items here).", "action": "Make quotation"}],
        "link": "/quotations?new=1&lead={lead_id}", "closed_by": ["quotation_created"], "escalations": [],
    },
    # the schedule (director's review, 12 Oct): the client's handover date and our target finish
    {
        "code": "handover_overdue", "number": 25, "event": "handover_overdue",
        "short": "Handover date passed", "ref": "{area}",
        "title": "Promised handover date passed and not confirmed",
        "recipients": [
            {"role": "site_engineer", "message": "{site}: {promised_by} promised to hand over {area} by {promised}; the supervisor has not confirmed it. Follow it up with the client.", "action": "Follow up"},
            {"role": "planning", "message": "{site}: {area} was promised by {promised} and is not handed over yet (client delay).", "action": "Replan"},
        ],
        "link": "/sites/{site_id}?tab=handover", "closed_by": ["handover_received"], "escalations": [],
    },
    {
        "code": "finish_overdue", "number": 26, "event": "finish_overdue",
        "short": "Target finish passed", "ref": "{area}",
        "title": "Target finish passed (our delay)",
        "recipients": [{"role": "site_engineer", "message": "{site}: {area} was due to finish by {target} (handed over {received}); it is not finished.", "action": "Finish the area"}],
        "link": "/sites/{site_id}?tab=handover", "closed_by": ["area_finished"],
        "escalations": [{"after_hours": 3 * D, "to": ["director"]}],
    },
    {
        "code": "travel_claim_ready", "number": 27, "event": "travel_claim_ready",
        "short": "Travel claim to approve", "ref": "{person} {month}",
        "title": "Monthly travel claim ready",
        "recipients": [
            {"role": "person", "message": "Your travel claim for {month} is ready: {km} km, {amount}. Add tolls and parking with the bill photo before your manager approves.", "info": True, "link": "/field/claims/{claim_id}"},
            {"role": "manager", "message": "Travel claim of {person} for {month}: {km} km, {amount} ({flagged} flagged days). Check the days and approve.", "action": "Approve", "link": "/field/claims/{claim_id}"},
        ],
        "link": "/field/claims/{claim_id}", "closed_by": ["claim_manager_approved"],
        "escalations": [{"after_hours": 3 * D, "to": ["director"]}],
    },
    {
        "code": "claim_manager_approved", "number": 28, "event": "claim_manager_approved",
        "short": "Travel claim for accounts", "ref": "{person} {month}",
        "title": "Travel claim approved by the manager",
        "recipients": [{"role": "accounts", "message": "Travel claim of {person} for {month} approved by the manager: {amount}. Approve the month.", "action": "Approve", "link": "/field/claims/{claim_id}"}],
        "link": "/field/claims/{claim_id}", "closed_by": ["claim_approved"],
        "escalations": [{"after_hours": 5 * D, "to": ["director"]}],
    },
    # the work order, billing and close-out review (16 Oct)
    {
        "code": "wo_amend", "number": 29, "event": "wo_amend",
        "short": "Ask the client to amend the work order", "ref": "{wo}",
        "title": "Work order deviation: ask the client to amend it",
        "recipients": [{"role": "salesperson", "message": "Work order {wo}: {topic}. Send the client: {text}", "action": "Send to the client"}],
        "link": "/work-orders/{wo_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "bill_not_submitted", "number": 30, "event": "bill_not_submitted",
        "short": "Bill not submitted in the window", "ref": "{bill}",
        "title": "Bill not submitted by the end of the client's billing window",
        "recipients": [
            {"role": "billing", "message": "{site}: {bill} was not submitted at site in the client's window ({window} of the month). Submit it or it waits a month.", "action": "Submit the bill"},
            {"role": "salesperson", "message": "{site}: {bill} missed the client's billing window ({window}).", "info": True},
        ],
        "link": "/billing/tracking?bill={ra_bill_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "bill_stuck", "number": 31, "event": "bill_stuck",
        "short": "Bill stuck at one step", "ref": "{bill}",
        "title": "Bill stuck at one step",
        "recipients": [{"role": "salesperson", "message": "{site}: {bill} has been at '{step}' for {days} days. Follow it up with the client.", "action": "Follow up"}],
        "link": "/billing/tracking?bill={ra_bill_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "bill_stuck_long", "number": 32, "event": "bill_stuck_long",
        "short": "Bill stuck: escalated", "ref": "{bill}",
        "title": "Bill stuck at one step (escalated)",
        "recipients": [{"role": "director", "message": "{site}: {bill} has been at '{step}' for {days} days; the salesperson was told.", "action": "Look into it"}],
        "link": "/billing/tracking?bill={ra_bill_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "payment_due", "number": 33, "event": "payment_due",
        "short": "Payment due today", "ref": "{bill}",
        "title": "Payment due",
        "recipients": [{"role": "accounts", "message": "{site}: {bill} is due on {due} ({how}), {amount} outstanding. Follow it up and log the call.", "action": "Follow up"}],
        "link": "/billing/payments?bill={ra_bill_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "payment_overdue", "number": 34, "event": "payment_overdue",
        "short": "Payment overdue", "ref": "{bill}",
        "title": "Payment overdue (5 days)",
        "recipients": [{"role": "salesperson", "message": "{site}: {bill} is overdue by {days} days (due {due}). Call the client.", "action": "Call the client"}],
        "link": "/billing/payments?bill={ra_bill_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "payment_overdue_long", "number": 35, "event": "payment_overdue_long",
        "short": "Payment overdue 30 days", "ref": "{bill}",
        "title": "Payment overdue (30 days)",
        "recipients": [
            {"role": "director", "message": "{site}: {bill} is overdue by {days} days (due {due}), {amount} outstanding.", "action": "Look into it"},
            {"role": "salesperson", "message": "{site}: {bill} is overdue by {days} days.", "info": True},
            {"role": "site_engineer", "message": "{site}: {bill} is overdue by {days} days: raise it with the client's site team.", "info": True},
        ],
        "link": "/billing/payments?bill={ra_bill_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "payment_promised", "number": 36, "event": "payment_promised",
        "short": "Promised payment date", "ref": "{bill}",
        "title": "The client's promised payment date",
        "recipients": [{"role": "accounts", "message": "{site}: {spoke_to} promised to pay {bill} by {promised}. Check it came in.", "action": "Check the payment"}],
        "link": "/billing/payments?bill={ra_bill_id}", "closed_by": [], "escalations": [],
    },
    {
        "code": "issue_raised", "number": 37, "event": "issue_raised",
        "short": "Issue on the site", "ref": "{issue}",
        "title": "Issue raised on a site",
        "recipients": [
            {"role": "person", "message": "{site}: {issue} {category}: {title}. It is yours.", "action": "Resolve it"},
            {"role": "site_engineer", "message": "{site}: {issue} {category}: {title}.", "info": True},
        ],
        "link": "/issues?open={issue_id}", "closed_by": ["issue_resolved"], "escalations": [],
    },
    {
        "code": "issue_overdue", "number": 38, "event": "issue_overdue",
        "short": "Issue past its due date", "ref": "{issue}",
        "title": "Issue past its due date",
        "recipients": [{"role": "person", "message": "{site}: {issue} {title} was due on {due}.", "action": "Resolve it"}],
        "link": "/issues?open={issue_id}", "closed_by": ["issue_resolved"],
        "escalations": [{"after_hours": 2 * D, "to": ["director"]}],
    },
]  # fmt: skip

# the order of the chain on a site's Process tab
CHAIN = [r["code"] for r in sorted(DEFAULT_RULES, key=lambda r: r["number"])]
ROLES = (
    "salesperson",
    "site_engineer",
    "supervisor",
    "planning",
    "billing",
    "accounts",
    "store_purchase",
    "estimator",
    "director",
    "office_admin",
    "author",
    "person",
    "manager",
)
DEFAULT_WASTAGE = {"raft": {"min": 5, "max": 7}, "footing": {"min": 12, "max": 15}}
