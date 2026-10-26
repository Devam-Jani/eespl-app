// /dev/ui: every shared component in each of its states (super admin only; the route is left out
// of the production build). The place to check a change to the look before it reaches a page.
import { useState } from "react";
import { useAuth } from "../auth";
import { inrCompact } from "../format";
import { Button, Card, DateField, EmptyState, Field, Icon, KpiCard, Legend, NavItem, ProgressBar, Select, Skeleton, StatusChip, Tabs } from "../ui/components";
import { FtInInput } from "../ui/FtIn";
import { MonthBars } from "../ui/MonthBars";
import { Drawer, Modal, useToast } from "../ui/Overlay";
import { Table } from "../ui/Table";
import { useTheme } from "../ui/theme";
import { STATUSES } from "../ui/tokens";

type Row = { id: number; site: string; done: number; late: boolean };
const ROWS: Row[] = [
  { id: 1, site: "DEMO Chripal House", done: 62, late: false },
  { id: 2, site: "DEMO Shela Heights", done: 88, late: false },
  { id: 3, site: "DEMO Prahladnagar tower", done: 41, late: true },
  { id: 4, site: "DEMO Bopal bungalow", done: 12, late: false },
];

export default function UiGallery() {
  const { me } = useAuth();
  const [theme, setTheme] = useTheme(me?.user.id ?? null, me?.user.ui_theme ?? null);
  const [kpi, setKpi] = useState(0);
  const [tab, setTab] = useState("one");
  const [ft, setFt] = useState("19");
  const [inch, setInch] = useState("14");
  const [sel, setSel] = useState("a");
  const [day, setDay] = useState("2026-10-23");
  const [modal, setModal] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const toast = useToast();
  if (!me?.roles.some((r) => r.code === "super_admin")) return <EmptyState title="For the super admin only" hint="The component page shows the look's building blocks." />;
  return (
    <div className="gallery">
      <header className="page-header">
        <h1>Components</h1>
        <div className="page-actions">
          <Button variant={theme === "dark" ? "primary" : "secondary"} onClick={() => setTheme("dark")}>
            Dark
          </Button>
          <Button variant={theme === "light" ? "primary" : "secondary"} onClick={() => setTheme("light")}>
            Light
          </Button>
        </div>
      </header>

      <Card title="Button">
        {(["primary", "secondary", "ghost", "danger"] as const).map((v) => (
          <div key={v} className="gallery-row">
            <span className="gallery-label">{v}</span>
            <Button variant={v}>Save</Button>
            <Button variant={v} loading>
              Save
            </Button>
            <Button variant={v} disabled>
              Save
            </Button>
            <Button variant={v} size="small">
              Small
            </Button>
          </div>
        ))}
      </Card>

      <Card title="Status chip and legend">
        <div className="gallery-row">
          {STATUSES.map((s) => (
            <StatusChip key={s} status={s} />
          ))}
          <StatusChip status="block">Late 9 days</StatusChip>
        </div>
        <Legend counts={{ done: 15, prog: 12, hold: 4, block: 1, idle: 8 }} />
      </Card>

      <section className="kpi-grid" aria-label="KPI cards">
        {["Order book", "Billed in October", "Overdue over 60 days", "Sites on track"].map((l, i) => (
          <KpiCard key={l} label={l} value={["₹4.82 Cr", "₹38.6 L", "₹12.4 L", "18 of 23"][i]} note="Pressed: shows its six months" active={kpi === i} onClick={() => setKpi(i)} />
        ))}
      </section>

      <Card title="Six months (MonthBars)">
        <MonthBars
          label="Billed per month"
          format={(v) => inrCompact(v * 1e5)}
          points={[
            { month: "May", value: 41 },
            { month: "Jun", value: 52 },
            { month: "Jul", value: null },
            { month: "Aug", value: 58 },
            { month: "Sep", value: 61 },
            { month: "Oct", value: 38.6 },
          ]}
        />
      </Card>

      <Card title="Nav item">
        <nav className="gallery-nav">
          <NavItem to="/dev/ui" label="Components (active)" />
          <NavItem to="/my-work" label="Approvals" count={3} />
          <NavItem to="/alerts" label="Alerts (default)" />
        </nav>
      </Card>

      <Card title="Table: sort, filter chips, paging, empty">
        <Table
          rows={ROWS}
          rowKey={(r) => r.id}
          pageSize={3}
          label="Sites"
          filters={[
            { key: "all", label: "All", test: () => true },
            { key: "late", label: "Late", test: (r) => r.late },
            { key: "none", label: "Billing due", test: () => false },
          ]}
          empty={{ title: "No site is due for billing", hint: "A site shows here when a finished stage is not billed." }}
          columns={[
            { key: "site", label: "Site", sort: (r) => r.site, render: (r) => r.site },
            { key: "done", label: "Work done", num: true, sort: (r) => r.done, render: (r) => `${r.done}%` },
            { key: "bar", label: "", render: (r) => <ProgressBar value={r.done} status={r.late ? "block" : undefined} /> },
          ]}
        />
      </Card>

      <Card title="Tabs">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "one", label: "Overview" },
            { key: "two", label: "3D building" },
            { key: "three", label: "Daily reports", count: 2 },
          ]}
        />
        <p className="muted">The open tab: {tab}. Arrow keys move between tabs.</p>
      </Card>

      <Card title="Inputs">
        <div className="grid-2">
          <Field label="Site name" hint="As on the work order">
            <input defaultValue="DEMO Chripal House" />
          </Field>
          <Field label="Quantity" error="Quantity must be 0 or more. Type a number of 0 or more.">
            <input defaultValue="-5" aria-invalid="true" />
          </Field>
          <Select
            label="Stage"
            value={sel}
            onChange={setSel}
            options={[
              { value: "a", label: "Surface prep" },
              { value: "b", label: "Primer + 2 coats" },
            ]}
          />
          <DateField label="Date" value={day} onChange={setDay} />
          <FtInInput label="Length measured (ft + in)" ft={ft} inch={inch} onChange={(f, i) => (setFt(f), setInch(i))} />
        </div>
      </Card>

      <Card title="Modal, drawer, toast with Undo">
        <div className="gallery-row">
          <Button onClick={() => setModal(true)}>Open a modal</Button>
          <Button onClick={() => setDrawer(true)}>Open a side drawer</Button>
          <Button onClick={() => toast.later("Approved the labour claim", () => undefined)}>Approve (with Undo)</Button>
          <Button onClick={() => toast.show({ text: "Something went wrong on our side. Reference: feedfeedfeedfeed", kind: "error" })}>A failure</Button>
        </div>
        {modal && (
          <Modal title="A modal" onClose={() => setModal(false)}>
            <p>Escape or the × closes it; focus comes back to the button.</p>
          </Modal>
        )}
        {drawer && (
          <Drawer title="A side drawer" onClose={() => setDrawer(false)}>
            <p>For a record's details beside a list.</p>
          </Drawer>
        )}
      </Card>

      <Card title="Skeleton, empty state, progress, icons">
        <div className="grid-2">
          <Skeleton lines={3} />
          <EmptyState title="No bills yet" hint="Raise the first RA bill from the measurement book." action={<Button variant="primary">Open the measurement book</Button>} />
          <div className="gallery-row">
            <ProgressBar value={62} />
            <ProgressBar value={88} status="done" />
            <ProgressBar value={41} status="block" />
          </div>
          <div className="gallery-row">
            {(["search", "back", "play", "alert", "camera", "day", "sites", "materials", "me"] as const).map((n) => (
              <Icon key={n} name={n} label={n} size={22} />
            ))}
          </div>
        </div>
      </Card>
    </div>
  );
}
