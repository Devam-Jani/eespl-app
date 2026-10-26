// Measuring from the drawing and billing from the sheet: click inside an outline (or trace one)
// and name it; answer each shared edge once; pick heights from the levels on a section; say how
// each work-order item is measured; then the measurement sheet in the billing team's layout, the
// RA bill made from it (its proforma, GST and checklist), and old Excel bills read back.
// Every number on the sheet lights up its outline on the drawing and in 3D.
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { errorText, inr, num } from "../format";
import { Button, Card, EmptyState, Field, PageSkeleton, Tabs } from "../ui/components";
import { Modal } from "../ui/Overlay";
import { CHART } from "../ui/tokens";
import { bbox, flatten, levelOf, outlinePath } from "./geom";
import { DrawnWallStart, ItemAreas, LineChoice, OutlineChooser, StudyForm, SumHeight } from "./Picking";
import { MaterialCheck, RegisterView, Revisions, SlipNew, SlipPanel, useShown } from "./Billing";
import type { SlipInfo } from "./Billing";
import type { Pt } from "./geom";

const Measure3D = lazy(() => import("./Measure3D").then((m) => ({ default: m.Measure3D })));

type Area = {
  id: number; code: string; name: string; kind: "area" | "slope"; outline: Pt[]; picked: boolean; layer: string | null; cad_file_id: number | null;
  area_sqm: string; periphery_m: string; trim_with: number[]; net_area_sqm: string; net_periphery_m: string;
  height_mm: string | null; height_source: string | null; height2_mm: string | null; height2_source: string | null; wall_top_mm: string;
  rise_mm: string | null; run_mm: string | null; slope_source: string | null; counts: Record<string, number>; billed: boolean;
  slope_mm: string | null; closed_gap_mm: string | null; drawn_length_m: string | null;
}; // prettier-ignore
type Edge = {
  id: number; area_a_id: number; area_b_id: number; a: string; b: string; length_m: string; line: number[]; answer: "both" | "open" | "weir" | "none" | null;
  weir_mm: string | null; manual: boolean; source: string | null;
}; // prettier-ignore
type Item = {
  wo_line_id: number; item_no: string | null; description: string; unit: string | null; qty: string | null; rate: string | null; per_layer: boolean; wo_layers: number;
  sac: string | null; parts: string[]; count_of: string | null; layers: number; layers_answer: "each" | "once" | null; areas: number[] | null; measured: boolean;
  skip: Record<string, string[]>; manual: Record<string, string>;
}; // prettier-ignore
type SheetRow = { id: number; code: string; seq: number; title: string | null; measured_on: string; status: string; imported_from: string | null; ra_bill_id: number | null };
type State = { site: { id: number; code: string; name: string }; drawings: { id: number; title: string; rev: number; unit_m: number }[]; areas: Area[]; edges: Edge[]; items: Item[]; sheets: SheetRow[]; sqft_per_sqm: string };
type Outline = { handle: string; layer: string; outline: Pt[] };
type Drawing = { id: number; outlines: Outline[]; texts: [number, number, number, string, string][] };
type Line = {
  kind: "area" | "line" | "deduction" | "not_done" | "total"; area_id: number | null; edge_id: number | null; wo_line_id: number | null; item_no: string | null; layer: number;
  part: string | null; particulars: string; no: string | null; length_m: string | null; width_m: string | null; height_m: string | null; qty: string | null;
  total: string | null; unit: string | null; formula: string | null; reason: string | null; id?: number; typed?: Record<string, string | null> | null; billed?: boolean;
}; // prettier-ignore
type Cum = {
  wo_line_id: number; item_no: string | null; description: string; unit: string | null; wo_qty: string | null; rate: string | null; previous: string;
  drawing: string; approved: string | null; this: string; upto: string; note: string | null;
}; // prettier-ignore
type Sheet = {
  id: number; code: string; title: string | null; measured_on: string; status: string; site_id: number; not_done: [number, number, number][]; imported_from: string | null;
  import_skipped: string[] | null; ra_bill_id: number | null; ra_code: string | null; lines: Line[]; questions: { kind: string; text: string; edge_id?: number; area_id?: number }[];
  cumulative: Cum[]; corrections: { field: string; old: string; new: string; remark: string | null; by: string; at: string; status: string }[]; sqft_per_sqm: string;
  way: string; options: Record<string, unknown>; slip: SlipInfo | null;
}; // prettier-ignore
type Check = { key: string; label: string; ok: boolean; detail: string[] };
type Bill = {
  id: number; code: string; status: string; title: string; proforma_no: string; proforma_on: string; measured_on: string | null; sheet_code: string | null;
  order: { basis: string; text: string }; buyer: { name: string | null; address: string | null; city: string | null; state: string | null; gstin: string | null };
  lines: { item_no: string | null; description: string; sac: string; unit: string; previous: string; this: string; cumulative: string; rate: string; amount: string }[];
  tax: { interstate: boolean; cgst_percent: string; sgst_percent: string; igst_percent: string; taxable: string; cgst: string; sgst: string; igst: string; round_off: string; total: string };
  warnings: string[]; checklist: Check[]; invoice_id: number | null; old_no: string | null;
  variations: { item_no: string | null; description: string; unit: string; rate: string; text: string }[];
}; // prettier-ignore

const PART_LABEL: Record<string, string> = { floor: "Floor", walls: "Side walls", tops: "Wall tops", slope: "Slope face", count: "Count" };
const ANSWER_LABEL = { both: "Wall on this edge, both faces", open: "Open (no wall)", weir: "Weir or cut wall", none: "Not a shared edge (drawn close, not one wall)" };
type Mode = "look" | "pick" | "trace" | "levels" | "line";
type LineFor = { purpose: "height" | "height2" | "slope" | "wall"; area?: Area; pair?: [number, number] };
type Pick = { areaId: number | null; edgeId: number | null };

export function MeasurePage() {
  const { id } = useParams();
  const siteId = Number(id);
  const [params, setParams] = useSearchParams();
  const [st, setSt] = useState<State | null>(null);
  const [drawing, setDrawing] = useState<Drawing | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(params.get("tab") ?? "areas");
  const [mode, setMode] = useState<Mode>("look");
  const [pick, setPick] = useState<Pick>({ areaId: null, edgeId: null });
  const [naming, setNaming] = useState<{ x?: number; y?: number; outline?: Pt[] } | null>(null);
  const [asking, setAsking] = useState<Edge | null>(null);
  const [levels, setLevels] = useState<string[]>([]);
  const [heightFor, setHeightFor] = useState<{ area: Area; what: "height" | "height2" | "slope" } | null>(null);
  const [view3d, setView3d] = useState(false);
  const [lineFor, setLineFor] = useState<LineFor | null>(null);
  const [lineAt, setLineAt] = useState<{ x: number; y: number } | null>(null);
  const [sumFor, setSumFor] = useState<{ area: Area; which: 1 | 2 } | null>(null);
  const [wallStart, setWallStart] = useState(false);
  const [studyNew, setStudyNew] = useState(false);
  const [slipNew, setSlipNew] = useState(false);
  const showRegister = params.get("register") === "1";
  const sheetId = params.get("sheet") ? Number(params.get("sheet")) : null;
  const billId = params.get("bill") ? Number(params.get("bill")) : null;

  const load = useCallback(async () => {
    try {
      setSt(await api<State>(`/api/measure/sites/${siteId}`));
    } catch (e) {
      setError(errorText(e));
    }
  }, [siteId]);
  useEffect(() => void load(), [load]);
  const fileId = st?.drawings[0]?.id ?? null;
  useEffect(() => {
    if (!fileId) return;
    api<Drawing>(`/api/measure/sites/${siteId}/drawing/${fileId}`).then(setDrawing, (e) => setError(errorText(e)));
  }, [siteId, fileId]);

  // the first edge not answered is asked as soon as it is found
  useEffect(() => {
    if (!st || asking) return;
    const open = st.edges.find((e) => e.answer === null);
    if (open && params.get("ask") !== "no") setAsking(open);
  }, [st]); // eslint-disable-line react-hooks/exhaustive-deps

  function open(next: Record<string, string | null>) {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: true });
  }

  function onLevel(text: string) {
    const next = [...levels, text];
    if (next.length === 2 && heightFor) {
      setLevels(next);
      setMode("look");
    } else setLevels(next.slice(-2));
  }

  if (!st) return error ? <div className="alert alert-error">{error}</div> : <PageSkeleton label="Loading the measurement" />;
  const areas3d = st.areas.map((a) => ({ id: a.id, code: a.code, outline: a.outline, kind: a.kind, depth_m: a.kind === "slope" ? Number(a.rise_mm ?? 300) / 1000 : Number(a.height_mm ?? 1000) / 1000 }));

  return (
    <div className="mb-page">
      <header className="page-header">
        <div>
          <Link to={`/sites/${siteId}`} className="muted">
            ← {st.site.code} {st.site.name}
          </Link>
          <h1>Measure and bill</h1>
        </div>
        <div className="row-actions">
          <Button variant={mode === "pick" ? "primary" : "secondary"} type="button" onClick={() => setMode(mode === "pick" ? "look" : "pick")} disabled={!drawing}>
            Click an area
          </Button>
          <Button variant={mode === "trace" ? "primary" : "secondary"} type="button" onClick={() => setMode(mode === "trace" ? "look" : "trace")} disabled={!drawing}>
            Trace an outline
          </Button>
          <Button variant="ghost" type="button" onClick={() => setView3d(!view3d)} disabled={!st.areas.length}>
            {view3d ? "Drawing" : "3D"}
          </Button>
          <Button variant="ghost" type="button" onClick={() => open({ register: showRegister ? null : "1" })}>
            Register
          </Button>
        </div>
      </header>
      {error && <div className="alert alert-error">{error}</div>}
      {!st.drawings.length && <EmptyState title="No drawing read for this site" hint="Upload the DWG under Drawings and let AutoCAD takeoff read it; then measure here." />}
      <div className="measure-grid">
        <div className="measure-canvas">
          {view3d ? (
            <Suspense fallback={<PageSkeleton label="Loading 3D" />}>
              <Measure3D areas={areas3d} selected={pick.areaId} />
            </Suspense>
          ) : drawing ? (
            <DrawingView
              drawing={drawing}
              areas={st.areas}
              edges={st.edges}
              mode={mode}
              pick={pick}
              levels={levels}
              onPoint={(x, y) => (mode === "line" ? setLineAt({ x, y }) : setNaming({ x, y }))}
              onTraced={(outline) => {
                setNaming({ outline });
                setMode("look");
              }}
              onLevel={onLevel}
              onArea={(areaId) => setPick({ areaId, edgeId: null })}
              onEdge={(e) => setAsking(e)}
            />
          ) : (
            st.drawings.length > 0 && !error && <PageSkeleton label="Reading the drawing" />
          )}
          <p className="muted measure-hint">
            {mode === "pick" && "Click inside an outline: its true area and periphery (arcs as arcs) are taken from the drawing."}
            {mode === "trace" && "Click the corners; click the first corner again (or double-click) to close the outline."}
            {mode === "levels" && `Click two levels on the section (${levels.length} of 2): ${levels.join(" and ")}`}
            {mode === "line" && "Click on the line: the lines near the click are listed to choose from (an arc is measured as an arc)."}
            {mode === "look" && "Drag to pan, wheel to zoom. Click an area or a number on the sheet to find it."}
          </p>
        </div>
        <div className="measure-side">
          <Tabs
            value={tab}
            onChange={(t) => {
              setTab(t);
              open({ tab: t });
            }}
            tabs={[
              { key: "areas", label: "Areas", count: st.areas.length },
              { key: "edges", label: "Edges", count: st.edges.filter((e) => !e.answer).length || undefined },
              { key: "items", label: "Items" },
              { key: "sheets", label: "Sheets", count: st.sheets.length },
              { key: "import", label: "Import" },
            ]}
          />
          {tab === "areas" && (
            <AreasPanel
              st={st}
              pick={pick}
              onPick={(areaId) => setPick({ areaId, edgeId: null })}
              onHeight={(area, what) => {
                setHeightFor({ area, what });
                setLevels([]);
                setMode("levels");
              }}
              onSum={(area, which) => setSumFor({ area, which })}
              onLine={(purpose, area) => {
                setLineFor({ purpose, area });
                setMode("line");
              }}
              reload={load}
            />
          )}
          {tab === "edges" && <EdgesPanel st={st} onAsk={setAsking} onWall={() => setWallStart(true)} />}
          {tab === "items" && <ItemsPanel st={st} reload={load} />}
          {tab === "sheets" && <SheetsPanel st={st} reload={load} onOpen={(s) => open({ sheet: String(s), bill: null })} onStudy={() => setStudyNew(true)} onSlip={() => setSlipNew(true)} />}
          {tab === "import" && <ImportPanel siteId={siteId} reload={load} />}
        </div>
      </div>
      {sheetId && (
        <SheetView
          key={sheetId}
          sheetId={sheetId}
          st={st}
          pick={pick}
          onPick={setPick}
          onBill={(b) => open({ bill: String(b) })}
          reload={load}
          onClose={() => open({ sheet: null })}
        />
      )}
      {showRegister && <RegisterView siteId={siteId} onOpen={(b) => open({ bill: String(b) })} onClose={() => open({ register: null })} />}
      {billId && <BillView key={billId} billId={billId} onClose={() => open({ bill: null })} />}
      {slipNew && (
        <SlipNew
          siteId={siteId}
          onClose={() => setSlipNew(false)}
          onDone={async (sid) => {
            setSlipNew(false);
            await load();
            open({ sheet: String(sid), bill: null });
          }}
        />
      )}
      {naming && (
        <NameArea
          siteId={siteId}
          fileId={fileId}
          at={naming}
          next={nextCode(st.areas)}
          onClose={() => setNaming(null)}
          onDone={async () => {
            setNaming(null);
            setMode("look");
            await load();
          }}
        />
      )}
      {asking && (
        <EdgeQuestion
          edge={asking}
          onClose={() => {
            setAsking(null);
            open({ ask: "no" });
          }}
          onDone={async () => {
            setAsking(null);
            await load();
          }}
        />
      )}
      {lineFor && lineAt && fileId && (
        <LineChoice
          siteId={siteId}
          fileId={fileId}
          x={lineAt.x}
          y={lineAt.y}
          askSection={lineFor.purpose !== "wall"}
          title={lineFor.purpose === "wall" ? "The wall drawn between the two areas" : lineFor.purpose === "slope" ? `${lineFor.area?.code}: the slope's line` : `${lineFor.area?.code}: a line's length as its height`}
          onClose={() => {
            setLineAt(null);
            setLineFor(null);
            setMode("look");
          }}
          onPick={async (l, section) => {
            if (lineFor.purpose === "wall" && lineFor.pair)
              await api(`/api/measure/sites/${siteId}/edges`, { method: "POST", json: { area_a_id: lineFor.pair[0], area_b_id: lineFor.pair[1], cad_file_id: fileId, line_handle: l.handle } });
            else if (lineFor.purpose === "slope" && lineFor.area) await api(`/api/measure/areas/${lineFor.area.id}/slope`, { method: "POST", json: { section, cad_file_id: fileId, line_handle: l.handle } });
            else if (lineFor.area)
              await api(`/api/measure/areas/${lineFor.area.id}/height`, { method: "POST", json: { section, cad_file_id: fileId, line_handle: l.handle, which: lineFor.purpose === "height2" ? 2 : 1 } });
            setLineAt(null);
            setLineFor(null);
            setMode("look");
            await load();
          }}
        />
      )}
      {sumFor && (
        <SumHeight
          area={sumFor.area}
          which={sumFor.which}
          onClose={() => setSumFor(null)}
          onDone={async () => {
            setSumFor(null);
            await load();
          }}
        />
      )}
      {wallStart && (
        <DrawnWallStart
          areas={st.areas}
          onClose={() => setWallStart(false)}
          onStart={(a, b) => {
            setWallStart(false);
            setLineFor({ purpose: "wall", pair: [a, b] });
            setMode("line");
          }}
        />
      )}
      {studyNew && (
        <StudyForm
          siteId={siteId}
          areas={st.areas}
          onClose={() => setStudyNew(false)}
          onDone={async (sid) => {
            setStudyNew(false);
            await load();
            open({ sheet: String(sid), bill: null });
          }}
        />
      )}
      {heightFor && levels.length === 2 && (
        <HeightConfirm
          area={heightFor.area}
          what={heightFor.what}
          levels={levels}
          onClose={() => {
            setHeightFor(null);
            setLevels([]);
          }}
          onDone={async () => {
            setHeightFor(null);
            setLevels([]);
            await load();
          }}
        />
      )}
    </div>
  );
}

/** An edge's path ([x1, y1, x2, y2, ...], straight or along an arc) as SVG points, y turned. */
export function edgePoints(line: number[]): string {
  const out: string[] = [];
  for (let i = 0; i + 1 < line.length; i += 2) out.push(`${line[i]},${-line[i + 1]}`);
  return out.join(" ");
}

function nextCode(areas: Area[]): string {
  const used = new Set(areas.map((a) => a.code));
  for (let i = 0; i < 26; i++) if (!used.has(String.fromCharCode(65 + i))) return String.fromCharCode(65 + i);
  return "";
}

// --- the drawing -----------------------------------------------------------------------------------

function DrawingView(props: {
  drawing: Drawing; areas: Area[]; edges: Edge[]; mode: Mode; pick: Pick; levels: string[];
  onPoint: (x: number, y: number) => void; onTraced: (o: Pt[]) => void; onLevel: (t: string) => void; onArea: (id: number) => void; onEdge: (e: Edge) => void;
}) { // prettier-ignore
  const { drawing, areas, edges, mode, pick, levels } = props;
  const svg = useRef<SVGSVGElement>(null);
  const extent = useMemo(() => {
    // the closed outlines (what is measured); the notes and sections far off are reached by zooming out
    const pts = drawing.outlines.length ? drawing.outlines.flatMap((o) => flatten(o.outline, 8)) : drawing.texts.map((t) => [t[0], t[1]] as [number, number]);
    const [x1, y1, x2, y2] = pts.length ? bbox(pts) : [0, 0, 10, 10];
    const m = Math.max(x2 - x1, y2 - y1) * 0.05 + 0.5;
    return { x: x1 - m, y: -(y2 + m), w: x2 - x1 + 2 * m, h: y2 - y1 + 2 * m };
  }, [drawing]);
  const [vb, setVb] = useState(extent);
  useEffect(() => setVb(extent), [extent]);
  // an area picked (in the list, or a number on the sheet): the drawing comes to it, with the
  // areas around it in view
  useEffect(() => {
    const a = areas.find((x) => x.id === pick.areaId);
    if (!a) return;
    const [x1, y1, x2, y2] = bbox(flatten(a.outline, 16));
    const m = Math.max(x2 - x1, y2 - y1) * 1.2 + 1;
    setVb({ x: x1 - m, y: -(y2 + m), w: x2 - x1 + 2 * m, h: y2 - y1 + 2 * m });
  }, [pick.areaId, areas]);
  // picking levels: the whole drawing, so the sections beside the plan are in view
  useEffect(() => {
    if (mode !== "levels") return;
    const pts = drawing.outlines.flatMap((o) => flatten(o.outline, 8)).concat(drawing.texts.map((t) => [t[0], t[1]] as [number, number]));
    const [x1, y1, x2, y2] = bbox(pts);
    const m = Math.max(x2 - x1, y2 - y1) * 0.04;
    setVb({ x: x1 - m, y: -(y2 + m), w: x2 - x1 + 2 * m, h: y2 - y1 + 2 * m });
  }, [mode, drawing]);
  const [trace, setTrace] = useState<Pt[]>([]);
  const drag = useRef<{ x: number; y: number; vb: typeof vb; moved: boolean } | null>(null);
  const taken = new Set(areas.map((a) => a.outline.map((p) => p.join(",")).join(";")));
  const unit = vb.w / 800; // a screen pixel, in metres

  function toDrawing(clientX: number, clientY: number): [number, number] {
    const el = svg.current!;
    const pt = el.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const p = pt.matrixTransform(el.getScreenCTM()!.inverse());
    return [p.x, -p.y];
  }
  function wheel(e: ReactWheelEvent) {
    const [x, y] = toDrawing(e.clientX, e.clientY);
    const f = e.deltaY > 0 ? 1.2 : 1 / 1.2;
    setVb((v) => ({ x: x - (x - v.x) * f, y: -y - (-y - v.y) * f, w: v.w * f, h: v.h * f }));
  }
  function down(e: ReactPointerEvent) {
    drag.current = { x: e.clientX, y: e.clientY, vb, moved: false };
  }
  function move(e: ReactPointerEvent) {
    const d = drag.current;
    if (!d || !svg.current) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.hypot(dx, dy) > 4) d.moved = true;
    if (!d.moved) return;
    const s = d.vb.w / svg.current.clientWidth;
    setVb({ ...d.vb, x: d.vb.x - dx * s, y: d.vb.y - dy * s });
  }
  function up(e: ReactPointerEvent) {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved) return;
    const [x, y] = toDrawing(e.clientX, e.clientY);
    if (mode === "pick" || mode === "line") props.onPoint(x, y);
    if (mode === "trace") {
      const first = trace[0];
      if (first && trace.length >= 3 && Math.hypot(first[0] - x, first[1] - y) < unit * 10) {
        props.onTraced(trace);
        setTrace([]);
      } else setTrace([...trace, [x, y, 0]]);
    }
  }

  return (
    <svg
      ref={svg}
      className={`measure-svg mode-${mode}`}
      viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
      onWheel={wheel}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onDoubleClick={() => {
        if (mode === "trace" && trace.length >= 3) {
          props.onTraced(trace);
          setTrace([]);
        }
      }}
      role="img"
      aria-label="The drawing's outlines and the measured areas"
    >
      <g className="m-outlines" strokeWidth={unit * 1.2}>
        {drawing.outlines.filter((o) => !taken.has(o.outline.map((p) => p.join(",")).join(";"))).map((o) => (
          <path key={o.handle} d={outlinePath(o.outline)} />
        ))}
      </g>
      {areas.map((a, i) => {
        const [x1, y1, x2, y2] = bbox(flatten(a.outline, 16));
        const on = pick.areaId === a.id;
        return (
          <g key={a.id} className={`m-area ${on ? "on" : ""}`} onPointerUp={() => mode === "look" && props.onArea(a.id)}>
            <path d={outlinePath(a.outline)} fill={CHART[i % 6]} stroke={CHART[i % 6]} strokeWidth={unit * (on ? 4 : 2)} />
            <text x={(x1 + x2) / 2} y={-(y1 + y2) / 2} fontSize={unit * 16} textAnchor="middle" dominantBaseline="middle" className="m-code">
              {a.code}
            </text>
          </g>
        );
      })}
      {edges.map((e) => (
        <polyline
          key={e.id}
          className={`m-edge ${e.answer ? "answered" : "open"} ${pick.edgeId === e.id ? "on" : ""}`}
          points={edgePoints(e.line)}
          strokeWidth={unit * (pick.edgeId === e.id ? 9 : 6)}
          onPointerUp={(ev) => {
            ev.stopPropagation();
            props.onEdge(e);
          }}
        >
          <title>
            {e.a}|{e.b}: {num(e.length_m, 3)} m {e.answer ? `(${ANSWER_LABEL[e.answer]})` : "(not answered)"}
          </title>
        </polyline>
      ))}
      <g className="m-texts">
        {drawing.texts.map(([x, y, h, t], i) => {
          const lv = levelOf(t) !== null;
          const chosen = levels.includes(t);
          return (
            <text
              key={i}
              x={x}
              y={-y}
              fontSize={Math.max(h, unit * 9)}
              className={`${lv && mode === "levels" ? "m-level" : ""} ${chosen ? "chosen" : ""}`}
              onPointerUp={(ev) => {
                if (mode === "levels" && lv) {
                  ev.stopPropagation();
                  props.onLevel(t);
                }
              }}
            >
              {t}
            </text>
          );
        })}
      </g>
      {trace.length > 0 && <polyline className="m-trace" points={trace.map((p) => `${p[0]},${-p[1]}`).join(" ")} strokeWidth={unit * 2} />}
    </svg>
  );
}

// --- the side panels -------------------------------------------------------------------------------

function AreasPanel(props: {
  st: State; pick: Pick; onPick: (id: number) => void; onHeight: (a: Area, w: "height" | "height2" | "slope") => void; onSum: (a: Area, which: 1 | 2) => void;
  onLine: (purpose: "height" | "slope", a: Area) => void; reload: () => Promise<void>;
}) { // prettier-ignore
  const { st, pick, onPick, onHeight, onSum, onLine, reload } = props;
  const codes = Object.fromEntries(st.areas.map((a) => [a.id, a.code]));
  const [err, setErr] = useState("");
  if (!st.areas.length) return <EmptyState title="No area yet" hint="Click an area on the drawing (or trace one) and name it: A, Q, R, as the billing team marks the drawing." />;
  async function remove(a: Area) {
    try {
      await api(`/api/measure/areas/${a.id}`, { method: "DELETE" });
      await reload();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <ul className="m-list">
      {err && <li className="alert alert-error">{err}</li>}
      {st.areas.map((a) => (
        <li key={a.id} className={pick.areaId === a.id ? "on" : ""}>
          <button type="button" className="m-list-head" onClick={() => onPick(a.id)}>
            <b>{a.code}</b> {a.name} {a.kind === "slope" && <span className="chip chip-prog">slope</span>} {a.billed && <span className="chip chip-done">billed</span>}
          </button>
          <dl className="m-figures">
            <dt>Area</dt>
            <dd>
              {num(a.net_area_sqm, 4)} sqm{a.trim_with.length > 0 && <span className="muted"> (as drawn {num(a.area_sqm, 4)}, less the overlap with {a.trim_with.map((i) => codes[i]).join(", ")})</span>}
            </dd>
            <dt>Periphery</dt>
            <dd>
              {num(a.net_periphery_m, 3)} m
              {a.closed_gap_mm && (
                <div className="m-why">
                  Drawn open ({num(a.closed_gap_mm, 1)} mm gap), closed by the app; its line as drawn is {num(a.drawn_length_m, 3)} m
                </div>
              )}
            </dd>
            {a.kind === "slope" ? (
              <>
                <dt>Slope</dt>
                <dd>{a.slope_source ?? <span className="muted">not picked</span>}</dd>
              </>
            ) : (
              <>
                <dt>Height</dt>
                <dd>{a.height_source ?? <span className="muted">not picked</span>}</dd>
                {a.height2_source && (
                  <>
                    <dt>Deep end</dt>
                    <dd>{a.height2_source}</dd>
                  </>
                )}
                <dt>Wall top</dt>
                <dd>{num(a.wall_top_mm, 0)} mm</dd>
              </>
            )}
            {Object.keys(a.counts).length > 0 && (
              <>
                <dt>Inside</dt>
                <dd>{Object.entries(a.counts).map(([k, n]) => `${n} on ${k.replace(":", " ")}`).join(", ")}</dd>
              </>
            )}
          </dl>
          {!a.billed && (
            <div className="row-actions">
              {a.kind === "slope" ? (
                <>
                  <Button size="small" type="button" onClick={() => onLine("slope", a)}>
                    Pick the slope's line
                  </Button>
                  <Button size="small" variant="ghost" type="button" onClick={() => onHeight(a, "slope")}>
                    Rise from two levels
                  </Button>
                </>
              ) : (
                <>
                  <Button size="small" type="button" onClick={() => onHeight(a, "height")}>
                    Pick the height on a section
                  </Button>
                  <Button size="small" variant="ghost" type="button" onClick={() => onSum(a, 1)}>
                    Add numbers
                  </Button>
                  <Button size="small" variant="ghost" type="button" onClick={() => onLine("height", a)}>
                    A line's length
                  </Button>
                  <Button size="small" variant="ghost" type="button" onClick={() => onHeight(a, "height2")}>
                    Deep end
                  </Button>
                </>
              )}
              <Button size="small" variant="ghost" type="button" onClick={() => remove(a)}>
                Remove
              </Button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function EdgesPanel({ st, onAsk, onWall }: { st: State; onAsk: (e: Edge) => void; onWall: () => void }) {
  const wall = (
    <div className="row-actions">
      <Button size="small" type="button" onClick={onWall} disabled={st.areas.length < 2}>
        A wall drawn on its own between two areas
      </Button>
    </div>
  );
  if (!st.edges.length)
    return (
      <>
        <EmptyState title="No shared edge" hint="Two areas side by side on one wall show here, to be answered once." />
        {wall}
      </>
    );
  return (
    <>
    {wall}
    <ul className="m-list">
      {st.edges.map((e) => (
        <li key={e.id}>
          <b>
            {e.a}|{e.b}
          </b>{" "}
          {num(e.length_m, 3)} m —{" "}
          {e.answer ? (
            <span>
              {ANSWER_LABEL[e.answer]}
              {e.answer === "weir" && ` (${num(e.weir_mm, 0)} mm)`}
            </span>
          ) : (
            <span className="chip chip-hold">not answered</span>
          )}{" "}
          <Button size="small" variant="ghost" type="button" onClick={() => onAsk(e)}>
            {e.answer ? "Change" : "Answer"}
          </Button>
          {e.manual && <div className="m-why">From {e.source}</div>}
        </li>
      ))}
    </ul>
    </>
  );
}

function ItemsPanel({ st, reload }: { st: State; reload: () => Promise<void> }) {
  const [err, setErr] = useState("");
  async function save(it: Item, change: Partial<Item>) {
    const next = { ...it, ...change };
    try {
      await api(`/api/measure/sites/${st.site.id}/items/${it.wo_line_id}`, {
        method: "PUT",
        json: { parts: next.parts, count_of: next.count_of, layers: next.layers, layers_answer: next.layers_answer, areas: next.areas, skip: next.skip, manual: next.manual },
      });
      await reload();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  const layersSeen = [...new Set(st.areas.flatMap((a) => Object.keys(a.counts)))];
  if (!st.items.length) return <EmptyState title="No work order" hint="The site's accepted work order gives the items and their rates." />;
  return (
    <ul className="m-list">
      {err && <li className="alert alert-error">{err}</li>}
      {st.items.map((it) => (
        <li key={it.wo_line_id}>
          <div>
            <b>{it.item_no}</b> {it.description.slice(0, 90)}{" "}
            <span className="muted">
              {inr(it.rate)} per {it.unit}
              {it.per_layer ? " per layer" : ""} · order {num(it.qty, 3)} {it.unit} · SAC {it.sac ?? "—"}
            </span>
          </div>
          <div className="m-parts">
            {Object.entries(PART_LABEL).map(([p, label]) => (
              <label key={p}>
                <input
                  type="checkbox"
                  checked={it.parts.includes(p)}
                  onChange={(e) => save(it, { parts: e.target.checked ? [...it.parts, p] : it.parts.filter((x) => x !== p), count_of: p === "count" && e.target.checked ? it.count_of ?? layersSeen[0] ?? null : it.count_of })}
                />{" "}
                {label}
              </label>
            ))}
          </div>
          <div className="row-actions">
            {it.parts.includes("count") && (
              <Field label="Count">
                <select value={it.count_of ?? ""} onChange={(e) => save(it, { count_of: e.target.value })}>
                  {layersSeen.map((k) => (
                    <option key={k} value={k}>
                      {k.replace(":", " ")}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="Layers">
              <select value={it.layers} onChange={(e) => save(it, { layers: Number(e.target.value) })}>
                {[1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </Field>
            <ItemAreas areas={st.areas} parts={it.parts} skip={it.skip} manual={it.manual} onSave={(skip, manual) => save(it, { skip, manual })} />
            {it.layers > 1 && !it.per_layer && (
              <Field label="The order's rate is not per layer: bill">
                <select value={it.layers_answer ?? ""} onChange={(e) => save(it, { layers_answer: (e.target.value || null) as Item["layers_answer"] })}>
                  <option value="">— answer —</option>
                  <option value="each">each layer</option>
                  <option value="once">the item once</option>
                </select>
              </Field>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

function SheetsPanel({ st, reload, onOpen, onStudy, onSlip }: { st: State; reload: () => Promise<void>; onOpen: (id: number) => void; onStudy: () => void; onSlip: () => void }) {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState("");
  const draft = st.sheets.some((s) => s.status === "draft");
  async function make() {
    try {
      const s = await api<Sheet>(`/api/measure/sites/${st.site.id}/sheets`, { method: "POST", json: { measured_on: on } });
      await reload();
      onOpen(s.id);
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <div>
      {err && <div className="alert alert-error">{err}</div>}
      <ul className="m-list">
        {st.sheets.map((s) => (
          <li key={s.id}>
            <button type="button" className="m-list-head" onClick={() => onOpen(s.id)}>
              <b>{s.code}</b> {s.title} <span className={`chip chip-${s.status === "billed" || s.status === "approved" ? "done" : s.status === "sent" || s.status === "study" ? "prog" : "idle"}`}>{s.status === "study" ? "study (not billed)" : s.status}</span>
            </button>
            <span className="muted">
              measured {s.measured_on}
              {s.imported_from ? ` · imported from ${s.imported_from}` : ""}
            </span>
          </li>
        ))}
      </ul>
      {!draft && (
        <div className="row-actions">
          <Field label="Measured on">
            <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
          </Field>
          <Button variant="primary" type="button" onClick={make}>
            New measurement sheet
          </Button>
        </div>
      )}
      <div className="row-actions">
        <Button type="button" onClick={onSlip} disabled={draft}>
          Bill from a slip
        </Button>
        <Button type="button" onClick={onStudy} disabled={!st.areas.length}>
          Compare another way
        </Button>
      </div>
    </div>
  );
}

function ImportPanel({ siteId, reload }: { siteId: number; reload: () => Promise<void> }) {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [sheet, setSheet] = useState<File | null>(null);
  const [proforma, setProforma] = useState<File | null>(null);
  const [out, setOut] = useState<{ sheet_code: string; ra_code: string; items: { item_no: string; description: string; qty: string; unit: string }[]; skipped: string[]; checks: string[] } | null>(null);
  const [err, setErr] = useState("");
  async function go() {
    const form = new FormData();
    form.set("measured_on", on);
    if (sheet) form.set("sheet", sheet);
    if (proforma) form.set("proforma", proforma);
    try {
      setOut(await api(`/api/measure/sites/${siteId}/import`, { method: "POST", form }));
      await reload();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <div>
      <p className="muted">The old Excel measurement sheet and proforma (before the app): their quantities become the previous of the first bill here.</p>
      <Field label="Old measurement sheet (.xlsx)">
        <input type="file" accept=".xlsx,.xlsm" onChange={(e) => setSheet(e.target.files?.[0] ?? null)} />
      </Field>
      <Field label="Old proforma (.xlsx)">
        <input type="file" accept=".xlsx,.xlsm" onChange={(e) => setProforma(e.target.files?.[0] ?? null)} />
      </Field>
      <Field label="Measured on">
        <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      </Field>
      <Button variant="primary" type="button" onClick={go} disabled={!sheet && !proforma}>
        Read them
      </Button>
      {err && <div className="alert alert-error">{err}</div>}
      {out && (
        <Card title={`Read: ${out.sheet_code}, ${out.ra_code}`} as="div">
          <table className="table compact">
            <thead>
              <tr>
                <th>Item</th>
                <th>Description</th>
                <th className="num">Previous qty</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {out.items.map((r) => (
                <tr key={r.item_no}>
                  <td>{r.item_no}</td>
                  <td>{r.description.slice(0, 60)}</td>
                  <td className="num">{num(r.qty, 3)}</td>
                  <td>{r.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Could not read ({out.skipped.length})</h3>
          {out.skipped.length ? (
            <ul className="m-skipped">
              {out.skipped.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">Every row was read.</p>
          )}
          {out.checks.length > 0 && (
            <>
              <h3>To check</h3>
              <ul className="m-skipped">
                {out.checks.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </>
          )}
        </Card>
      )}
    </div>
  );
}

// --- the questions ---------------------------------------------------------------------------------

function NameArea({ siteId, fileId, at, next, onClose, onDone }: { siteId: number; fileId: number | null; at: { x?: number; y?: number; outline?: Pt[] }; next: string; onClose: () => void; onDone: () => Promise<void> }) {
  const [code, setCode] = useState(next);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"area" | "slope">("area");
  const [handle, setHandle] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const clicked = at.x !== undefined && at.y !== undefined && fileId !== null && !at.outline;
  async function save() {
    try {
      await api(`/api/measure/sites/${siteId}/areas`, { method: "POST", json: { cad_file_id: fileId, x: at.x, y: at.y, outline: at.outline, handle: clicked ? handle : null, code, name, kind } });
      await onDone();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Modal title="Name this area" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        {clicked && <OutlineChooser siteId={siteId} fileId={fileId} x={at.x as number} y={at.y as number} value={handle} onChange={setHandle} />}
        <Field label="Letter on the drawing">
          <input value={code} maxLength={10} onChange={(e) => setCode(e.target.value.toUpperCase())} required />
        </Field>
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Swimming pool" required autoFocus />
        </Field>
        <Field label="Kind">
          <select value={kind} onChange={(e) => setKind(e.target.value as "area" | "slope")}>
            <option value="area">Floor with walls (pool, tank, sunk area)</option>
            <option value="slope">Slope</option>
          </select>
        </Field>
        {err && <div className="alert alert-error">{err}</div>}
        <div className="row-actions">
          <Button variant="primary" type="submit" disabled={clicked && !handle}>
            Measure it
          </Button>
          <Button variant="ghost" type="button" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function EdgeQuestion({ edge, onClose, onDone }: { edge: Edge; onClose: () => void; onDone: () => Promise<void> }) {
  const [answer, setAnswer] = useState<Edge["answer"]>(edge.answer);
  const [weir, setWeir] = useState(edge.weir_mm ?? "");
  const [err, setErr] = useState("");
  async function save() {
    try {
      await api(`/api/measure/edges/${edge.id}/answer`, { method: "POST", json: { answer, weir_mm: answer === "weir" ? weir : null } });
      await onDone();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Modal title={`${edge.a}|${edge.b}: ${num(edge.length_m, 3)} m shared`} onClose={onClose}>
      <p>Wall on this edge?</p>
      <div className="m-answers" role="radiogroup" aria-label="Wall on this edge?">
        {(["both", "open", "weir", "none"] as const).map((a) => (
          <label key={a} className={answer === a ? "on" : ""}>
            <input type="radio" name="edge" checked={answer === a} onChange={() => setAnswer(a)} />{" "}
            {a === "both" ? "Yes, both faces" : a === "open" ? "Open (no wall)" : a === "weir" ? "Weir or cut wall" : "Not a shared edge (drawn close, not one wall)"}
          </label>
        ))}
      </div>
      {answer === "weir" && (
        <Field label="The weir's height (mm)">
          <input className="m-weir" inputMode="decimal" value={weir} onChange={(e) => setWeir(e.target.value)} />
        </Field>
      )}
      <p className="muted">Asked once: the answer changes both areas' walls and wall tops on the sheet.</p>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="row-actions">
        <Button variant="primary" type="button" onClick={save} disabled={!answer || (answer === "weir" && !weir)}>
          Save the answer
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Later
        </Button>
      </div>
    </Modal>
  );
}

function HeightConfirm({ area, what, levels, onClose, onDone }: { area: Area; what: "height" | "height2" | "slope"; levels: string[]; onClose: () => void; onDone: () => Promise<void> }) {
  const [section, setSection] = useState("Section Y-Y");
  const [run, setRun] = useState("");
  const [err, setErr] = useState("");
  const [a, b] = levels;
  const va = levelOf(a) ?? 0;
  const vb = levelOf(b) ?? 0;
  const [top, bottom] = va >= vb ? [a, b] : [b, a];
  async function save() {
    try {
      if (what === "slope") await api(`/api/measure/areas/${area.id}/slope`, { method: "POST", json: { section, top, bottom, run_mm: run, run_source: section } });
      else await api(`/api/measure/areas/${area.id}/height`, { method: "POST", json: { section, top, bottom, which: what === "height2" ? 2 : 1 } });
      await onDone();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Modal title={`${area.code} ${area.name}: ${what === "slope" ? "the slope's rise" : what === "height2" ? "the deep end" : "its height"}`} onClose={onClose}>
      <Field label="Section">
        <input value={section} onChange={(e) => setSection(e.target.value)} />
      </Field>
      <p className="m-source">
        {section}: {top} to {bottom} = {Math.abs(va - vb)} mm
      </p>
      {what === "slope" && (
        <Field label="Horizontal run (mm), from the section">
          <input inputMode="decimal" value={run} onChange={(e) => setRun(e.target.value)} required />
        </Field>
      )}
      {err && <div className="alert alert-error">{err}</div>}
      <div className="row-actions">
        <Button variant="primary" type="button" onClick={save} disabled={what === "slope" && !run}>
          Use it
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

// --- the sheet -------------------------------------------------------------------------------------

function SheetView({ sheetId, st, pick, onPick, onBill, reload, onClose }: { sheetId: number; st: State; pick: Pick; onPick: (p: Pick) => void; onBill: (id: number) => void; reload: () => Promise<void>; onClose: () => void }) {
  const [s, setS] = useState<Sheet | null>(null);
  const [err, setErr] = useState("");
  const [billing, setBilling] = useState(false);
  useShown("m-sheet", s !== null);
  const load = useCallback(() => api<Sheet>(`/api/measure/sheets/${sheetId}`).then(setS, (e) => setErr(errorText(e))), [sheetId]);
  useEffect(() => void load(), [load, st]);
  if (!s) return err ? <div className="alert alert-error">{err}</div> : <PageSkeleton label="Building the sheet" />;
  const draft = s.status === "draft";
  const code = Object.fromEntries(st.areas.map((a) => [a.id, a.code]));
  const nd = new Set(s.not_done.map((k) => k.join(",")));

  async function act(path: string, json?: unknown) {
    try {
      setErr("");
      setS(await api<Sheet>(path, { method: "POST", json }));
      await reload();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  const pair = new Map<string, Line>();
  for (const ln of s.lines) if (ln.kind !== "area" && ln.area_id && ln.wo_line_id) pair.set(`${ln.area_id},${ln.wo_line_id},${ln.layer}`, ln);
  const cell = (ln: Line, v: string | null, d: number) => (
    <td className="num">
      {v === null ? (
        ""
      ) : (
        <button type="button" className="m-num" onClick={() => onPick({ areaId: ln.area_id, edgeId: ln.edge_id })} title={ln.formula ?? ln.reason ?? ""}>
          {num(v, d)}
        </button>
      )}
    </td>
  );

  return (
    <Card
      id="m-sheet"
      title={`${s.code} · measurement sheet · measured ${s.measured_on}`}
      actions={
        <div className="row-actions">
          <span className={`chip chip-${s.status === "draft" ? "idle" : s.status === "sent" ? "prog" : "done"}`}>{s.status}</span>
          <Button size="small" type="button" onClick={() => downloadFile(`/api/measure/sheets/${s.id}/xlsx`)}>
            Excel
          </Button>
          <Button size="small" type="button" onClick={() => downloadFile(`/api/measure/sheets/${s.id}/pdf`)}>
            PDF
          </Button>
          {draft && (
            <Button size="small" variant="primary" type="button" onClick={() => act(`/api/measure/sheets/${s.id}/send`)} disabled={s.questions.length > 0}>
              Send to the client
            </Button>
          )}
          {s.status === "approved" && !s.ra_bill_id && (
            <Button size="small" variant="primary" type="button" onClick={() => setBilling(true)}>
              Make the RA bill
            </Button>
          )}
          {s.ra_bill_id && (
            <Button size="small" type="button" onClick={() => onBill(s.ra_bill_id!)}>
              {s.ra_code}
            </Button>
          )}
          <Button size="small" variant="ghost" type="button" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      {err && <div className="alert alert-error">{err}</div>}
      {s.questions.length > 0 && (
        <div className="alert alert-warn">
          <b>To answer before it can be sent:</b>
          <ul>
            {s.questions.map((q, i) => (
              <li key={i}>{q.text}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="muted">
        1 sqm = {s.sqft_per_sqm} sqft · sizes in metres · Click a number to find its outline.
      </p>
      {s.slip ? (
        <SlipPanel sheetId={s.id} slip={s.slip} items={st.items} draft={draft} onChanged={(out) => setS(out as Sheet)} />
      ) : (
        <p className={`m-way ${s.status === "study" ? "study" : ""}`}>{s.way}</p>
      )}
      <div className="table-wrap">
        <table className="table compact m-sheet">
          <thead>
            <tr>
              <th>Sr / WO item</th>
              <th>Particulars</th>
              <th className="num">No</th>
              <th className="num">Length</th>
              <th className="num">Width</th>
              <th className="num">Height / Depth</th>
              <th className="num">Qty</th>
              <th className="num">Total qty</th>
              <th>Unit</th>
              {draft && <th />}
            </tr>
          </thead>
          <tbody>
            {s.lines.map((ln, i) =>
              ln.kind === "area" ? (
                <tr key={i} className={`m-area-row ${pick.areaId === ln.area_id ? "on" : ""}`}>
                  <td>{ln.area_id ? code[ln.area_id] : ""}</td>
                  <td colSpan={draft ? 9 : 8}>
                    <button type="button" className="m-num" onClick={() => onPick({ areaId: ln.area_id, edgeId: null })}>
                      {ln.particulars}
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={i} className={`${ln.kind === "deduction" ? "m-ded" : ""} ${ln.kind === "total" ? "m-total" : ""} ${pick.areaId === ln.area_id && ln.area_id ? "on" : ""}`}>
                  <td>{ln.item_no}</td>
                  <td>
                    {ln.particulars}
                    {(ln.reason || ln.formula) && <div className="m-why">{ln.kind === "deduction" ? ln.reason : ln.formula}</div>}
                  </td>
                  {ln.kind === "not_done" ? (
                    <>
                      <td colSpan={4} />
                      <td className="num">–</td>
                      <td className="num">–</td>
                    </>
                  ) : (
                    <>
                      {cell(ln, ln.no, 0)}
                      {cell(ln, ln.length_m, 3)}
                      {cell(ln, ln.width_m, 3)}
                      {cell(ln, ln.height_m, 3)}
                      {cell(ln, ln.qty, 4)}
                      {cell(ln, ln.total, 3)}
                    </>
                  )}
                  <td>{ln.unit}</td>
                  {draft && (
                    <td>
                      {s.slip && ln.id && ln.kind !== "total" && (
                        <Button size="small" variant="ghost" type="button" onClick={async () => setS(await api<Sheet>(`/api/measure/sheets/${s.id}/slip-lines/${ln.id}`, { method: "DELETE" }))}>
                          Remove
                        </Button>
                      )}
                      {ln.area_id && ln.wo_line_id && (ln.kind === "not_done" || pair.get(`${ln.area_id},${ln.wo_line_id},${ln.layer}`) === ln) && (
                        <Button
                          size="small"
                          variant="ghost"
                          type="button"
                          onClick={() => act(`/api/measure/sheets/${s.id}/not-done`, { area_id: ln.area_id, wo_line_id: ln.wo_line_id, layer: ln.layer, not_done: !nd.has(`${ln.area_id},${ln.wo_line_id},${ln.layer}`) })}
                        >
                          {ln.kind === "not_done" ? "Done after all" : "Work not done"}
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
      {/* a phone: each line as a card, its sizes in one row */}
      <ul className="m-cards" aria-label="The sheet's lines">
        {s.lines.map((ln, i) =>
          ln.kind === "area" ? (
            <li key={i} className="m-card-area">
              {ln.particulars}
            </li>
          ) : (
            <li key={i} className={`m-card ${ln.kind === "deduction" ? "m-ded" : ""}`} onClick={() => onPick({ areaId: ln.area_id, edgeId: ln.edge_id })}>
              <div>
                <b>{ln.item_no}</b> {ln.particulars}
              </div>
              {ln.kind === "not_done" ? (
                <div className="m-card-qty">–</div>
              ) : (
                <>
                  <div className="m-why">
                    {[ln.no && `No ${num(ln.no, 0)}`, ln.length_m && `L ${num(ln.length_m, 3)}`, ln.width_m && `W ${num(ln.width_m, 3)}`, ln.height_m && `H ${num(ln.height_m, 3)}`].filter(Boolean).join(" × ")}
                    {ln.qty && ` = ${num(ln.qty, 4)}`}
                  </div>
                  {/* a line converted once per item (a slip, "a total line") has no total of its own:
                      its quantity is what it adds, as in the table's Qty column */}
                  <div className="m-card-qty">{ln.total !== null ? `${num(ln.total, 3)} ${ln.unit ?? ""}` : ln.qty !== null ? `Qty ${num(ln.qty, 4)}${s.slip && ln.unit ? ` ${ln.unit}` : ""}` : "—"}</div>
                </>
              )}
            </li>
          ),
        )}
      </ul>
      <h3>Abstract</h3>
      <table className="table compact m-abstract">
        <thead>
          <tr>
            <th>WO item</th>
            <th>Description</th>
            <th>Unit</th>
            <th className="num">Previous</th>
            <th className="num">On the drawing</th>
            <th className="num">Approved by the client</th>
            <th className="num">This bill</th>
            <th className="num">Up to date</th>
            <th className="num">WO qty</th>
          </tr>
        </thead>
        <tbody>
          {s.cumulative.map((r) => (
            <tr key={r.wo_line_id}>
              <td>{r.item_no}</td>
              <td>
                {r.description.slice(0, 80)}
                {r.note && <div className="m-why m-corrected">{r.note}</div>}
              </td>
              <td>{r.unit}</td>
              <td className="num">{num(r.previous, 3)}</td>
              <td className="num">{num(r.drawing, 3)}</td>
              <td className="num">{r.approved === null ? "—" : num(r.approved, 3)}</td>
              <td className="num">
                <b>{num(r.this, 3)}</b>
              </td>
              <td className="num">{num(r.upto, 3)}</td>
              <td className="num">{num(r.wo_qty, 3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* a phone: each item as a card, every column a row (the table's right-hand columns do not fit) */}
      <ul className="m-cards m-abstract-cards" aria-label="The sheet's abstract">
        {s.cumulative.map((r) => (
          <li key={r.wo_line_id} className="m-card">
            <div>
              <b>{r.item_no}</b> {r.description.slice(0, 80)} <span className="muted">({r.unit})</span>
              {r.note && <div className="m-why m-corrected">{r.note}</div>}
            </div>
            <dl className="m-card-rows">
              <dt>Previous</dt>
              <dd>{num(r.previous, 3)}</dd>
              <dt>On the drawing</dt>
              <dd>{num(r.drawing, 3)}</dd>
              <dt>Approved by the client</dt>
              <dd>{r.approved === null ? "—" : num(r.approved, 3)}</dd>
              <dt>This bill</dt>
              <dd>
                <b>{num(r.this, 3)}</b>
              </dd>
              <dt>Up to date</dt>
              <dd>{num(r.upto, 3)}</dd>
              <dt>WO qty</dt>
              <dd>{num(r.wo_qty, 3)}</dd>
            </dl>
          </li>
        ))}
      </ul>
      {s.corrections.length > 0 && (
        <>
          <h3>The client's corrections</h3>
          <ul className="m-skipped">
            {s.corrections.map((c, i) => (
              <li key={i}>
                {c.field}: {num(c.old, 3)} → {num(c.new, 3)} by {c.by}, {new Date(c.at).toLocaleString("en-IN")} — {c.remark} ({c.status})
              </li>
            ))}
          </ul>
        </>
      )}
      {s.import_skipped && s.import_skipped.length > 0 && (
        <>
          <h3>Not read from the old sheet</h3>
          <ul className="m-skipped">
            {s.import_skipped.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </>
      )}
      {billing && (
        <MakeBill
          sheet={s}
          onClose={() => setBilling(false)}
          onDone={async (id) => {
            setBilling(false);
            await load();
            await reload();
            onBill(id);
          }}
        />
      )}
    </Card>
  );
}

function MakeBill({ sheet, onClose, onDone }: { sheet: Sheet; onClose: () => void; onDone: (id: number) => Promise<void> }) {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [basis, setBasis] = useState<"wo" | "verbal">("wo");
  const [by, setBy] = useState("");
  const [when, setWhen] = useState("");
  const [err, setErr] = useState("");
  async function save() {
    try {
      const b = await api<Bill>(`/api/measure/sheets/${sheet.id}/bill`, { method: "POST", json: { proforma_on: on, basis, verbal_by: by || null, verbal_on: when || null } });
      await onDone(b.id);
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Modal title={`The RA bill from ${sheet.code}`} onClose={onClose}>
      <Field label="Proforma date" hint={on < sheet.measured_on ? `Before the measurement (${sheet.measured_on})` : undefined}>
        <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      </Field>
      <Field label="Billed against">
        <select value={basis} onChange={(e) => setBasis(e.target.value as "wo" | "verbal")}>
          <option value="wo">The work order</option>
          <option value="verbal">A verbal order</option>
        </select>
      </Field>
      {basis === "verbal" && (
        <>
          <Field label="Confirmed by (the client's role or person)">
            <input value={by} onChange={(e) => setBy(e.target.value)} required />
          </Field>
          <Field label="Confirmed on">
            <input type="date" value={when} onChange={(e) => setWhen(e.target.value)} required />
          </Field>
        </>
      )}
      <p className="muted">Quantities from the sheet as the client approved them; rates from the work order only.</p>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="row-actions">
        <Button variant="primary" type="button" onClick={save}>
          Make the proforma
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

// --- the bill --------------------------------------------------------------------------------------

function BillView({ billId, onClose }: { billId: number; onClose: () => void }) {
  const [b, setB] = useState<Bill | null>(null);
  const [err, setErr] = useState("");
  const [done, setDone] = useState("");
  useShown("m-bill", b !== null);
  const load = useCallback(() => api<Bill>(`/api/measure/bills/${billId}`).then(setB, (e) => setErr(errorText(e))), [billId]);
  useEffect(() => void load(), [load]);
  if (!b) return err ? <div className="alert alert-error">{err}</div> : <PageSkeleton label="Loading the bill" />;
  const ready = b.checklist.every((c) => c.ok);
  async function send() {
    try {
      await api(`/api/finance/ra-bills/${billId}/submit`, { method: "POST" });
      await load();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  async function toInvoice() {
    try {
      const inv = await api<{ number: string }>(`/api/measure/bills/${billId}/tax-invoice`, { method: "POST", json: {} });
      setDone(`Tax invoice ${inv.number} made, with the proforma's lines`);
      await load();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  const t = b.tax;
  return (
    <Card
      id="m-bill"
      title={`${b.title} ${b.proforma_no} · ${b.code}${b.old_no ? ` (was ${b.old_no} in the old files)` : ""}`}
      actions={
        <div className="row-actions">
          <span className={`chip chip-${b.status === "draft" ? "idle" : b.status === "invoiced" ? "done" : "prog"}`}>{b.status}</span>
          <Button size="small" type="button" onClick={() => downloadFile(`/api/measure/bills/${b.id}/pdf`)}>
            PDF
          </Button>
          {b.status === "draft" && (
            <Button size="small" variant="primary" type="button" onClick={send} disabled={!ready}>
              Send the bill
            </Button>
          )}
          {["submitted", "certified_by_client", "certified"].includes(b.status) && !b.invoice_id && (
            <Button size="small" variant="primary" type="button" onClick={toInvoice}>
              Make it the tax invoice
            </Button>
          )}
          <Button size="small" variant="ghost" type="button" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      {err && <div className="alert alert-error">{err}</div>}
      {done && <div className="alert alert-ok">{done}</div>}
      {b.warnings.map((w) => (
        <div key={w} className="alert alert-warn">
          {w}
        </div>
      ))}
      {b.variations.length > 0 && (
        <div className="alert alert-info">
          <b>Variations in this bill, for the client to agree:</b>
          <ul>
            {b.variations.map((v) => (
              <li key={v.text}>{v.text}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="m-bill-head">
        <div>
          <h3>Proforma</h3>
          <b>{b.proforma_no}</b>
          <br />
          Date {b.proforma_on}
          {b.measured_on && <span className="muted"> · measured {b.measured_on}</span>}
        </div>
        <div>
          <h3>Buyer</h3>
          <b>{b.buyer.name}</b>
          <br />
          {b.buyer.address}
          <br />
          {[b.buyer.city, b.buyer.state].filter(Boolean).join(", ")} · GSTIN {b.buyer.gstin ?? "—"}
        </div>
        <div>
          <h3>Order</h3>
          {b.order.text}
          <br />
          <span className="muted">from {b.sheet_code}</span>
        </div>
      </div>
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Item</th>
              <th>Description</th>
              <th>SAC</th>
              <th>Unit</th>
              <th className="num">Previous</th>
              <th className="num">This bill</th>
              <th className="num">Cumulative</th>
              <th className="num">Rate (work order)</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {b.lines.map((ln, i) => (
              <tr key={i}>
                <td>{ln.item_no}</td>
                <td>{ln.description.slice(0, 80)}</td>
                <td>{ln.sac}</td>
                <td>{ln.unit}</td>
                <td className="num">{num(ln.previous, 3)}</td>
                <td className="num">{num(ln.this, 3)}</td>
                <td className="num">{num(ln.cumulative, 3)}</td>
                <td className="num">{inr(ln.rate)}</td>
                <td className="num">{inr(ln.amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={8}>Basic (taxable)</td>
              <td className="num">{inr(t.taxable)}</td>
            </tr>
            {t.interstate ? (
              <tr>
                <td colSpan={8}>IGST {num(t.igst_percent, 0)}% (outside the state)</td>
                <td className="num">{inr(t.igst)}</td>
              </tr>
            ) : (
              <>
                <tr>
                  <td colSpan={8}>CGST {num(t.cgst_percent, 1)}%</td>
                  <td className="num">{inr(t.cgst)}</td>
                </tr>
                <tr>
                  <td colSpan={8}>SGST {num(t.sgst_percent, 1)}%</td>
                  <td className="num">{inr(t.sgst)}</td>
                </tr>
              </>
            )}
            <tr>
              <td colSpan={8}>Round off</td>
              <td className="num">{inr(t.round_off)}</td>
            </tr>
            <tr>
              <td colSpan={8}>
                <b>Grand total</b>
              </td>
              <td className="num">
                <b>{inr(t.total)}</b>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <Revisions billId={b.id} canEdit />
      <MaterialCheck billId={b.id} />
      <h3>Billing checklist</h3>
      <ul className="m-checks">
        {b.checklist.map((c) => (
          <li key={c.key} className={c.ok ? "ok" : "bad"}>
            <span className={`chip chip-${c.ok ? "done" : "block"}`}>{c.ok ? "OK" : "Fix"}</span> {c.label}
            {c.detail.length > 0 && <div className="m-why">{c.detail.join("; ")}</div>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
