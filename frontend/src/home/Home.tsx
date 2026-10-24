// The dashboard (EESPL UI v1, Figma 01): four key numbers for the person's own dashboard (each
// switches the six-month chart below to itself), the live X-ray building of a chosen site,
// "Needs you today" with one-tap actions and Undo, and the active sites. Every role gets this
// layout with its own numbers (GET /api/home); the detailed dashboards stay one click away.
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errorText, inrCompact } from "../format";
import type { Building } from "../xray/geometry";
import type { XNode } from "../xray/XrayView";
import { Button, Card, EmptyState, Field, KpiCard, ProgressBar, Skeleton, StatusChip } from "../ui/components";
import { MonthBars, type MonthPoint } from "../ui/MonthBars";
import { useToast } from "../ui/Overlay";
import { Table } from "../ui/Table";
import type { Status } from "../ui/tokens";

const XrayView = lazy(() => import("../xray/XrayView"));

type Kpi = { key: string; label: string; value: number | string | null; of?: number; unit: string; note?: string; series: MonthPoint[] };
type Action = { label: string; primary?: boolean; link?: string; method?: "POST" | "PUT"; path?: string; body?: unknown; done?: string };
type Need = { key: string; tag: string; tone: Status; title: string; link: string; actions: Action[] };
type SiteRow = { id: number; code: string; name: string; city: string | null; progress: number; status: Status; status_label: string; billed: number | null; order: number | null; next: string | null; late: boolean; billing_due: boolean; has_building: boolean };
type Home = { date: string; demo: boolean; dashboard: string | null; kpis: Kpi[]; needs: Need[]; sites: SiteRow[]; building: { site_id: number; name: string } | null };
type Model = { building: Building | null; nodes: XNode[]; site_progress?: number };

export function formatKpi(k: Pick<Kpi, "value" | "unit" | "of">): string {
  if (k.value === null || k.value === undefined) return "—";
  if (typeof k.value === "string") return k.value;
  if (k.unit === "inr") return inrCompact(k.value);
  if (k.unit === "pct") return `${Math.round(k.value)}%`;
  if (k.unit === "of") return `${k.value} of ${k.of ?? 0}`;
  return k.value.toLocaleString("en-IN");
}

function greeting(d: Date): string {
  const h = d.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

const LATER = (uid: string, day: string) => `eespl.later.${uid}.${day}`;
function laterSet(uid: string, day: string): Set<string> {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(LATER(uid, day)) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

export default function Home() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [data, setData] = useState<Home | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chart, setChart] = useState(0);
  const [siteId, setSiteId] = useState<number | null>(null);
  const [model, setModel] = useState<Model | null>(null);
  const [roomsFirst, setRoomsFirst] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const uid = me?.user.id ?? "";
  const role = me?.roles[0]?.name ?? "";

  const load = useCallback(() => {
    api<Home>("/api/home").then(
      (d) => {
        setData(d);
        setHidden(laterSet(uid, d.date));
        setSiteId((s) => s ?? d.building?.site_id ?? null);
      },
      (e) => setError(errorText(e) || "The dashboard could not be loaded."),
    );
  }, [uid]);
  useEffect(load, [load]);
  useEffect(() => {
    if (!siteId) return;
    setModel(null);
    api<Model>(`/api/sites/${siteId}/model`).then(setModel, () => setModel({ building: null, nodes: [] }));
  }, [siteId]);

  const needs = useMemo(() => (data?.needs ?? []).filter((n) => !hidden.has(n.key)), [data, hidden]);
  const buildingSites = (data?.sites ?? []).filter((s) => s.has_building);
  const shownSite = data?.sites.find((s) => s.id === siteId);
  const money = (data?.sites ?? []).some((s) => s.billed !== null);

  function later(n: Need) {
    if (!data) return;
    const next = new Set(hidden).add(n.key);
    setHidden(next);
    try {
      window.localStorage.setItem(LATER(uid, data.date), JSON.stringify([...next]));
    } catch {
      // storage blocked: hidden until the page reloads
    }
  }
  function act(n: Need, a: Action) {
    if (a.link) return navigate(a.link);
    setHidden((h) => new Set(h).add(n.key));
    toast.later(
      `${a.done ?? a.label}: ${n.title}`,
      async () => {
        try {
          await api(a.path!, { method: a.method ?? "POST", json: a.body });
          load();
        } catch (e) {
          const t = errorText(e);
          if (t) toast.show({ text: t, kind: "error" });
          setHidden((h) => {
            const x = new Set(h);
            x.delete(n.key);
            return x;
          });
        }
      },
      6000,
      () =>
        setHidden((h) => {
          const x = new Set(h);
          x.delete(n.key);
          return x;
        }),
    );
  }

  if (error) return <div className="alert alert-error">{error}</div>;
  const k = data?.kpis[chart];
  const today = data ? new Date(`${data.date}T12:00:00`) : new Date();

  return (
    <div className="home">
      <header className="home-head">
        <p className="muted">
          {today.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
          {data?.demo ? " · DEMO data" : ""}
        </p>
        <h1>
          {greeting(new Date())}
          {role ? `, ${role}` : ""}
        </h1>
      </header>

      <section className="kpi-grid" aria-label="Key numbers">
        {data
          ? data.kpis.map((x, i) => <KpiCard key={x.key} label={x.label} value={formatKpi(x)} note={x.note} active={i === chart} onClick={() => setChart(i)} />)
          : [0, 1, 2, 3].map((i) => <Skeleton key={i} height={110} radius={16} />)}
      </section>

      {k && (
        <Card
          title={k.label}
          actions={
            <span className="muted small">
              Last 6 months · tap a number above to switch ·{" "}
              <Link to="/dashboard/details" className="small">
                More numbers
              </Link>
            </span>
          }
        >
          {k.series.length ? <MonthBars points={k.series} label={`${k.label}, last six months`} format={(v) => formatKpi({ value: v, unit: k.unit, of: k.of })} /> : <p className="muted">This number has no month-by-month history.</p>}
        </Card>
      )}

      <div className="home-row">
        <Card className="home-building" aria-label="Live building">
          <header className="card-head home-building-head">
            <h2 className="card-title">Live building{shownSite || data?.building ? ` · ${shownSite?.name ?? data?.building?.name}` : ""}</h2>
            {buildingSites.length > 1 && (
              <Field label="Site shown in 3D" bare>
                <select value={siteId ?? ""} onChange={(e) => setSiteId(Number(e.target.value))} aria-label="Site shown in 3D">
                  {buildingSites.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Button aria-pressed={roomsFirst} onClick={() => setRoomsFirst(!roomsFirst)}>
              Rooms first
            </Button>
            {siteId && (
              <Link className="home-open" to={`/sites/${siteId}?tab=3d`}>
                Open the site →
              </Link>
            )}
          </header>
          {!data || (siteId && !model) ? (
            <Skeleton height={400} radius={0} />
          ) : model?.building ? (
            <Suspense fallback={<Skeleton height={400} radius={0} />}>
              <XrayView
                site={{ id: siteId!, name: shownSite?.name ?? data.building?.name ?? "", code: shownSite?.code ?? "", progress: model.site_progress ?? shownSite?.progress ?? 0 }}
                building={model.building}
                nodes={model.nodes}
                bare
                roomsFirst={roomsFirst}
                next={shownSite?.next}
              />
            </Suspense>
          ) : (
            <EmptyState title="No building in 3D yet" hint="Build it from the site's AutoCAD drawing (Site > 3D building)." />
          )}
        </Card>

        <Card className="home-needs" aria-label="Needs you today" title="Needs you today" actions={<span className="muted">{needs.length} open</span>}>
          {!data ? (
            <Skeleton height={90} lines={3} />
          ) : needs.length === 0 ? (
            <EmptyState title="Nothing waits on you" hint={<Link to="/my-work">Everything on your list is under Approvals</Link>} />
          ) : (
            needs.map((n) => (
              <article key={n.key} className="need">
                <p className={`need-tag tone-${n.tone}`}>{n.tag}</p>
                <Link to={n.link} className="need-title">
                  {n.title}
                </Link>
                <div className="need-actions">
                  {n.actions.map((a) => (
                    <Button key={a.label} variant={a.primary ? "primary" : "secondary"} onClick={() => act(n, a)}>
                      {a.label}
                    </Button>
                  ))}
                  <Button onClick={() => later(n)}>Later</Button>
                </div>
              </article>
            ))
          )}
        </Card>
      </div>

      <Card title="Active sites">
        {!data ? (
          <Skeleton height={44} lines={4} />
        ) : (
          <Table
            rows={data.sites}
            rowKey={(s) => s.id}
            label="Active sites"
            onOpen={(s) => navigate(`/sites/${s.id}`)}
            cards
            filters={[
              { key: "all", label: "All", test: () => true },
              { key: "late", label: "Late", test: (s) => s.late },
              { key: "billing", label: "Billing due", test: (s) => s.billing_due },
            ]}
            empty={{ title: "No active sites", hint: "Sites you are on show here once they start." }}
            columns={[
              {
                key: "site",
                label: "Site",
                sort: (s) => s.name,
                render: (s) => (
                  <div className="cell-two">
                    <Link to={`/sites/${s.id}`} onClick={(e) => e.stopPropagation()}>
                      {s.name}
                    </Link>
                    <span className="muted small">{[s.code, s.city].filter(Boolean).join(" · ")}</span>
                  </div>
                ),
              },
              {
                key: "done",
                label: "Work done",
                sort: (s) => s.progress,
                render: (s) => (
                  <div className="cell-two">
                    <ProgressBar value={s.progress} status={s.status === "done" ? "done" : s.status === "block" ? "block" : undefined} label={`${s.name}: ${s.progress}% done`} />
                    <span className="muted small">{s.progress}%</span>
                  </div>
                ),
              },
              { key: "status", label: "Status", sort: (s) => s.status_label, render: (s) => <StatusChip status={s.status}>{s.status_label}</StatusChip> },
              ...(money
                ? [{ key: "billed", label: "Billed of order", sort: (s: SiteRow) => s.billed ?? 0, render: (s: SiteRow) => (s.order ? `${inrCompact(s.billed ?? 0)} of ${inrCompact(s.order)}` : inrCompact(s.billed ?? 0)) }]
                : []),
              { key: "next", label: "Next step", render: (s) => <span className="soft">{s.next ?? "—"}</span> },
            ]}
          />
        )}
      </Card>
    </div>
  );
}
