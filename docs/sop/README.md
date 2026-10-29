# Role SOPs

One button-by-button guide per role, written from the code and the running app. Roles, never
names. The pictures come from the DEMO data of the training company.

Each SOP is assembled from two kinds of source:

- `docs/sop/<role>.md`: the role's own text. It says what the role is for, its day in pages, its
  handoffs, the common mistakes and the quick card.
- `docs/sop/pages/<page>.md`: one section per page of the app, shared by every role that opens it.

`python -m app.cli sops` builds the SOPs:

- `data/sop/EESPL SOP - <Role>.pdf` and `.docx`, in the gitignored data folder;
- `data/sop/EESPL Quick start - <Role>.pdf`: 10-15 pages to hand over with the login (first login, the
  quick card, the role's main pages with one picture each). The pages are the first of the role's day,
  or the front matter's `quick: /a, /b, ...` (at most 8);
- the in-app reader: Help > How to, and the "How to" link on each page.

`scripts/sop-screens.mjs` takes the pictures on the training company. Each role logs in as its own
DEMO user. Office roles are shot 1600 px wide; site and phone roles 390 px. The button being
explained gets a red box.

## A page file: `docs/sop/pages/<slug>.md`

The slug is the route without its first `/`, with `/` turned into `-`. So `/settings/help` is
`settings-help.md`, and `/my-work` is `my-work.md`.

```markdown
---
page: /daily-reports
title: Daily reports
routes: /daily-reports, /my-site/:id/report
mark: New report
---
What the page shows, in two or three sentences.

**On the page**
- **New report**: opens the form for today's report on the chosen site. {perm: dpr.edit}
- **Site** (field): the site the report is for. Only your sites are listed.
- **Approve**: marks the report approved; the site engineer is notified. {perm: dpr.approve}

**Rules**
- A report can be edited until it is approved. After that, only ... {perm: dpr.approve}

**What happens next**
- ...

**Hands off**
- Receives: ...
- Passes on: ...

**When it goes wrong**
- "Exact message the app shows": what it means and what to do.
```

**Front matter**

- `routes`: every route of the app this section covers. That is the menu page and its detail pages
  (`/sites/:id`, `/sites/:id/zones` ...). Every route the app has must be covered by exactly one
  page file. The tests check this.
- `mark`: the exact label of the button that gets the red box in the screenshot. It must be
  visible on the page itself, without opening anything. It is optional.

**The body**

- A line ending in `{perm: a.b, c.d}` is kept only for the roles holding at least one of those
  permissions. The tag is taken out. Use it on list lines, for buttons and rules that only some
  roles have.
- Labels are written in **bold**, exactly as on screen, with the same capitals.

## A role file: `docs/sop/<role>.md`

```markdown
---
role: site_engineer
title: Site engineer
width: 390
---
## What this role is for
...
{{access}}
{{first-login}}
## Your day, page by page
@page /my-work
@page /field
...
## Handoffs
## Common mistakes
## Quick card
```

The builder fills in three markers:

- `{{access}}`: the role's pages, and what it never sees, from the real permissions (the same rules
  as Settings > Who sees what).
- `{{first-login}}`: the shared "first login" section, with the two-step part for the roles that
  must use it.
- `@page /route`: that page's section, its lines filtered for the role.

Every page the role may open must have an `@page` line. The tests fail when a new page is added to
the app without SOP text.
