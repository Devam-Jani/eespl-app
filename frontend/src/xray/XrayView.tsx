// The X-ray building: the real building from the AutoCAD drawing, see-through, every room we
// waterproof in its stage colour. Staff (3D tab), the client (portal: X-ray and realistic, no
// tools) and the director's dashboard tile (compact) use it.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { errorText } from "../format";
import type { Category, NodeStatus } from "../pages/site/three/colors";
import { CATEGORY_LABEL, LATE_COLOR, STATUS_COLORS } from "../pages/site/three/colors";
import { composeSnapshot } from "../pages/site/three/snapshot";
import type { SnapLegendItem } from "../pages/site/three/snapshot";
import type { Building, TimelineRow, XRoom } from "./geometry";
import type { IfcElement } from "./ifc";
import { tooBig } from "./ifc";
import { addDays, bloomOn, daysBetween, replayRange, statusAt } from "./geometry";
import type { Placed } from "./labels";
import { placeLabels } from "./labels";
import { roomsFirstByDefault, showsSectionLine } from "./views";
import type { Label, Mode, Preset, RoomState } from "./scene";
import { XrayScene } from "./scene";
import { Button, buttonClass, Field, Icon } from "../ui/components";

export type XNode = { id: number; name: string; kind: string; status: NodeStatus; timeline?: TimelineRow[] };
type Props = {
  site: { id: number; name: string; code: string; progress: number };
  building: Building;
  nodes: XNode[];
  portal?: boolean;
  cover?: boolean; // the portal's cover view: a slow turn until touched
  compact?: boolean; // the dashboard tile: the picture only
  onPick?: (nodeId: number) => void;
  canLink?: boolean; // planning: link IFC elements to our places
  ifcHeaders?: Record<string, string>; // the portal's
  bare?: boolean; // the dashboard card: the building, its legend and progress, no tools
  roomsFirst?: boolean; // set from outside (the dashboard card's own button)
  selected?: number | null; // the room picked in the list beside it: outlined in white
  floor?: number | null; // the floor open (cutaway), set from outside
  onFloor?: (level: number | null) => void;
  next?: string | null; // "Next: hold point, floor 5"
};

const today = () => new Date().toISOString().slice(0, 10);
const ORDER: Exclude<Category, "rollup">[] = ["done", "progress", "hold", "blocked", "not_started", "none"];
// the design's short names (the same everywhere: chips, tables, charts, this legend)
const LEGEND_LABEL: Record<Exclude<Category, "rollup">, string> = { done: "Done", progress: "In progress", hold: "Hold point", blocked: "Blocked", not_started: "Not started", none: "Not ours" };
const MODE_LABEL: Record<Mode, string> = { xray: "X-ray", status: "Status", real: "Realistic" };
const prefersBloom = (setting: Building["settings"]["bloom"]) => bloomOn(setting, navigator.hardwareConcurrency || 4, /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent) || window.innerWidth < 600);

export default function XrayView({ site, building, nodes, portal, cover, compact, onPick, canLink, ifcHeaders, bare, roomsFirst: roomsFirstOut, selected, floor, onFloor, next }: Props) {
  const hasDrawing = Object.keys(building.types).length > 0;
  const [source, setSource] = useState<"drawing" | "bim">(hasDrawing ? "drawing" : "bim");
  const [ifcEls, setIfcEls] = useState<IfcElement[] | null>(null);
  const [ifcNote, setIfcNote] = useState<string | null>(null);
  const [allowBig, setAllowBig] = useState(false);
  const [links, setLinks] = useState<Record<string, number>>(building.ifc_links ?? {});
  const [linkFor, setLinkFor] = useState<IfcElement | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<XrayScene | null>(null);
  const [mode, setMode] = useState<Mode>("xray");
  const [cutIn, setCutIn] = useState<number | null>(null);
  const cut = floor !== undefined ? floor : cutIn;
  const setCut = (v: number | null) => {
    setCutIn(v);
    onFloor?.(v);
  };
  const [explode, setExplode] = useState(false);
  const [roomsFirstIn, setRoomsFirst] = useState(roomsFirstByDefault(portal));
  const roomsFirst = roomsFirstOut ?? roomsFirstIn;
  const [labels, setLabels] = useState<Label[]>([]);
  const [fps, setFps] = useState(0);
  const [bloom, setBloom] = useState<Building["settings"]["bloom"]>(building.settings.bloom);
  const [hover, setHover] = useState<{ room: XRoom; x: number; y: number } | null>(null);
  const [recording, setRecording] = useState(false);
  const byNode = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const now = today();
  const [first, last] = useMemo(() => replayRange(nodes.map((n) => n.timeline ?? []), now), [nodes, now]);
  const span = Math.max(0, daysBetween(first, last));
  const [day, setDay] = useState(span); // the slider: days from the first start (span = today)
  const [playing, setPlaying] = useState(false);
  const on = addDays(first, Math.min(day, span));

  const states = useMemo(() => {
    const out = new Map<number, RoomState>();
    for (const id of new Set([...building.rooms.map((r) => r.node_id), ...Object.values(links)])) {
      const n = byNode.get(id);
      if (!n) continue;
      const s = statusAt(n.timeline ?? [], on, now, n.status);
      out.set(id, { category: s.category, late: s.late });
    }
    return out;
  }, [building.rooms, byNode, on, now, links]);

  // the scene: made once per building, kept while the page stays
  useEffect(() => {
    if (!canvas.current) return;
    const s = new XrayScene(canvas.current, building, { mode: "xray", bloom: prefersBloom(building.settings.bloom), autoTurn: !!cover });
    s.autoBloom = building.settings.bloom === "auto";
    s.onFrame = compact ? null : (l, f) => {
      setLabels(l);
      setFps(Math.round(f));
    };
    scene.current = s;
    (window as unknown as { __xray?: XrayScene }).__xray = s; // for the frame-rate measurement and checks
    const ro = new ResizeObserver(() => s.resize());
    ro.observe(canvas.current);
    return () => {
      ro.disconnect();
      s.dispose();
      scene.current = null;
    };
  }, [building, cover, compact]);
  useEffect(() => scene.current?.setStates(states, links), [states, links]);
  // the client's BIM file: loaded on first use (web-ifc is its own chunk), never above the laptop
  // limit unless asked
  const big = !!building.ifc && tooBig((building.ifc.size_mb ?? 0) * 1024 * 1024, building.ifc.max_mb);
  useEffect(() => {
    const s = scene.current;
    if (!s) return;
    if (source !== "bim" || !building.ifc) {
      s.setIfc(null);
      return;
    }
    if (big && !allowBig) return;
    if (ifcEls) {
      s.setIfc(ifcEls, links);
      return;
    }
    setIfcNote("Reading the BIM file in the browser…");
    import("./ifcLoad")
      .then((m) => m.loadIfc(building.ifc!.url, ifcHeaders))
      .then((els) => {
        setIfcEls(els);
        setIfcNote(null);
      })
      .catch((e) => setIfcNote(`The BIM file could not be read: ${errorText(e)}`));
    // links repaint through setStates; a new file or source reloads
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, ifcEls, big, allowBig, building.ifc]);

  async function link(el: IfcElement, nodeId: number | null) {
    try {
      const r = await api<{ ifc_links: Record<string, number> }>(`/api/sites/${site.id}/building/ifc-links`, { method: "PUT", json: { element: el.expressID, node_id: nodeId } });
      setLinks(r.ifc_links);
      if (ifcEls) scene.current?.setIfc(ifcEls, r.ifc_links);
      setLinkFor(null);
    } catch (e) {
      setIfcNote(errorText(e));
    }
  }
  useEffect(() => scene.current?.setMode(mode), [mode]);
  useEffect(() => scene.current?.setCutaway(cut), [cut]);
  useEffect(() => scene.current?.setExplode(explode), [explode]);
  useEffect(() => scene.current?.setRoomsFirst(roomsFirst), [roomsFirst]);
  useEffect(() => scene.current?.setSelected(selected ?? null), [selected, building]);
  const stage = useRef<HTMLDivElement>(null);
  const placed: Placed[] = useMemo(() => {
    const w = stage.current?.clientWidth ?? 800;
    return placeLabels(labels, w < 500 ? 10 : 12, { width: w, height: stage.current?.clientHeight ?? 600 });
  }, [labels]);
  useEffect(() => {
    if (bloom === "auto") scene.current?.setBloom(prefersBloom("auto"), true);
    else scene.current?.setBloom(bloom === "on", false);
  }, [bloom]);

  // play: the whole replay in about 15 s, then stop at today
  useEffect(() => {
    if (!playing) return;
    const step = Math.max(1, Math.round(span / 225));
    const id = window.setInterval(() => {
      setDay((d) => {
        if (d + step >= span) {
          setPlaying(false);
          return span;
        }
        return d + step;
      });
    }, 66);
    return () => window.clearInterval(id);
  }, [playing, span]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { late: 0 };
    for (const s of states.values()) {
      c[s.category] = (c[s.category] ?? 0) + 1;
      if (s.late) c.late += 1;
    }
    return c;
  }, [states]);
  const legend: SnapLegendItem[] = [...ORDER.filter((k) => counts[k] || k !== "none").map((k) => ({ label: LEGEND_LABEL[k], color: STATUS_COLORS[k], count: counts[k] ?? 0 })), ...(counts.late ? [{ label: "Late", color: LATE_COLOR, count: counts.late, outline: true }] : [])];
  const floors = [...building.floors].sort((a, b) => b.level - a.level);

  function saveImage() {
    const src = canvas.current;
    if (!src) return;
    const out = composeSnapshot(src, src.width / src.clientWidth, {
      siteName: site.name,
      siteCode: site.code,
      percent: site.progress,
      date: new Date(`${on}T12:00:00`),
      labels: labels.map((l) => ({ text: `${l.text} ${l.sub}`, x: l.x, y: l.y, tower: false, late: false })),
      legend,
      note: `${MODE_LABEL[mode]} view from the AutoCAD drawing${on < now ? `, status on ${on}` : ""}`,
    });
    const a = document.createElement("a");
    a.href = out.toDataURL("image/png");
    a.download = `${site.code}-3d-${on}.png`;
    a.click();
  }

  /** The replay as a short WebM, recorded from the canvas in the browser (at most 30 s). */
  function saveVideo() {
    const src = canvas.current;
    if (!src || recording || typeof MediaRecorder === "undefined") return;
    const type = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t)) ?? "video/webm";
    const rec = new MediaRecorder(src.captureStream(30), { mimeType: type, videoBitsPerSecond: 4_000_000 });
    const parts: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size && parts.push(e.data);
    rec.onstop = () => {
      setRecording(false);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob(parts, { type: "video/webm" }));
      a.download = `${site.code}-replay.webm`;
      a.click();
    };
    setRecording(true);
    setDay(0);
    rec.start(250);
    window.setTimeout(() => setPlaying(true), 600);
    const stopAt = window.setTimeout(() => rec.state === "recording" && rec.stop(), 30_000);
    let seenPlaying = false;
    const watch = window.setInterval(() => {
      if (rec.state !== "recording") return window.clearInterval(watch);
      const now = !!document.querySelector(".xray[data-playing='true']");
      seenPlaying ||= now;
      // the replay ran and stopped at today: hold a second on it, then stop
      if (seenPlaying && !now) {
        window.clearInterval(watch);
        window.setTimeout(() => {
          window.clearTimeout(stopAt);
          if (rec.state === "recording") rec.stop();
        }, 1200);
      }
    }, 300);
  }

  function move(e: React.PointerEvent) {
    const s = scene.current;
    if (!s || compact) return;
    const room = s.pick(e.clientX, e.clientY);
    const r = canvas.current!.getBoundingClientRect();
    setHover(room ? { room, x: e.clientX - r.left, y: e.clientY - r.top } : null);
  }
  function click(e: React.MouseEvent) {
    if (source === "bim") {
      const el = scene.current?.pickIfc(e.clientX, e.clientY);
      if (el && canLink && !portal) setLinkFor(el);
      else if (el && links[String(el.expressID)] != null && onPick && !portal) onPick(links[String(el.expressID)]);
      return;
    }
    const room = scene.current?.pick(e.clientX, e.clientY);
    if (room && onPick && !portal) onPick(room.node_id);
  }
  const view = (p: Preset) => {
    setCut(null);
    scene.current?.view(p);
  };
  const hn = hover ? byNode.get(hover.room.node_id) : null;
  const hs = hover ? states.get(hover.room.node_id) : null;

  return (
    <div className={`xray xray-${mode}${compact ? " xray-compact" : ""}${bare ? " xray-bare" : ""}`} data-playing={playing ? "true" : "false"}>
      {!compact && !bare && (
        <div className="xray-bar">
          {building.ifc && (
            <div className="xray-seg" role="group" aria-label="Source">
              {hasDrawing && (
                <Button size="small" className={source === "drawing" ? "active" : ""} onClick={() => setSource("drawing")}>
                  Drawing
                </Button>
              )}
              <Button size="small" className={source === "bim" ? "active" : ""} onClick={() => setSource("bim")} title={building.ifc.filename ?? undefined}>
                BIM (IFC)
              </Button>
            </div>
          )}
          <div className="xray-seg" role="group" aria-label="View mode">
            {(portal ? (["xray", "real"] as Mode[]) : (["xray", "status", "real"] as Mode[])).map((m) => (
              <Button key={m} variant={mode === m ? "primary" : "secondary"} aria-pressed={mode === m} onClick={() => setMode(m)}>
                {MODE_LABEL[m]}
              </Button>
            ))}
          </div>
          <Button aria-pressed={roomsFirst} onClick={() => setRoomsFirst(!roomsFirst)} title="Dim the building, light up our rooms">
            Rooms first
          </Button>
          <Button aria-pressed={explode} onClick={() => setExplode(!explode)} title="Spread the floors apart">
            Explode
          </Button>
          <span className="xray-spacer" />
          <Field label="Open a floor (cutaway)" bare>
            <select className="xray-floor" value={cut ?? ""} onChange={(e) => setCut(e.target.value === "" ? null : Number(e.target.value))} aria-label="Open a floor (cutaway)">
              <option value="">Floor: All floors</option>
              {floors.map((f) => (
                <option key={f.level} value={f.level}>
                  Floor: {f.name}
                </option>
              ))}
            </select>
          </Field>
          <details className="xray-more">
            <summary className={buttonClass({ variant: "secondary", icon: true })} aria-label="More view tools: camera, save image, glow" title="Camera, save image, glow">
              <span aria-hidden="true">⋯</span>
            </summary>
            <div className="xray-more-menu">
              <div className="xray-seg" role="group" aria-label="Camera">
                {(["reset", "top", "front", "iso"] as Preset[]).map((p) => (
                  <Button key={p} size="small" onClick={() => view(p)}>
                    {p === "reset" ? "Reset" : p[0].toUpperCase() + p.slice(1)}
                  </Button>
                ))}
              </div>
              <Button size="small" onClick={saveImage}>
                Save image
              </Button>
              {!portal && (
                <Field label="Glow" bare>
                  <select value={bloom} onChange={(e) => setBloom(e.target.value as typeof bloom)} aria-label="Glow" title={`Glow (${fps} fps)`}>
                    <option value="auto">Glow: auto</option>
                    <option value="on">Glow: on</option>
                    <option value="off">Glow: off</option>
                  </select>
                </Field>
              )}
            </div>
          </details>
        </div>
      )}
      <div className="xray-stage" ref={stage}>
        <canvas ref={canvas} onPointerMove={move} onPointerLeave={() => setHover(null)} onClick={click} aria-label={`${site.name}: the building in 3D`} />
        {placed.map((l, i) =>
          l.hidden && hover?.room.node_id !== l.nodeId ? null : (
            <div key={i} className={`xray-label${l.dy ? " xray-label-moved" : ""}`} style={{ left: l.x, top: l.y + l.dy }}>
              {l.text}
              <small>{l.sub}</small>
              {l.dy !== 0 && <i className="xray-leader" style={{ height: Math.abs(l.dy) - l.h / 2, [l.dy < 0 ? "top" : "bottom"]: "100%" }} />}
            </div>
          ),
        )}
        {hover && hs && (
          <div className="xray-tip" style={{ left: hover.x + 14, top: hover.y + 10 }}>
            <b>{hover.room.name}</b>
            <div>
              {building.floors.find((f) => f.level === hover.room.level)?.name} · {CATEGORY_LABEL[hs.category]}
              {hs.late ? " · late" : ""}
            </div>
            {hn && on >= now && <div>{Math.round(hn.status.percent)}% done{hn.status.current_step ? ` · now: ${hn.status.current_step}` : ""}</div>}
            <div className="muted">
              {(hover.room.area_sqm ?? 0).toFixed(2)} sqm{hover.room.sunk_m ? ` · sunk ${Math.round(hover.room.sunk_m * 1000)} mm` : ""}
              {hover.room.wp_height_m ? ` · up the walls ${Math.round(hover.room.wp_height_m * 1000)} mm` : ""}
            </div>
          </div>
        )}
        {source === "bim" && big && !allowBig && (
          <div className="xray-over">
            <p>
              This BIM file is {building.ifc?.size_mb} MB, more than an office laptop opens comfortably (the limit for this site is {building.ifc?.max_mb} MB). It may take minutes and freeze the browser.
            </p>
            <Button size="small" onClick={() => setAllowBig(true)}>
              Open it anyway
            </Button>
          </div>
        )}
        {ifcNote && <div className="xray-over">{ifcNote}</div>}
        {linkFor && (
          <div className="xray-over xray-link">
            <b>{linkFor.type.replace("IFC", "")}</b> {linkFor.name ?? `#${linkFor.expressID}`}
            <Field label="Our place">
              <select value={links[String(linkFor.expressID)] ?? ""} onChange={(e) => void link(linkFor, e.target.value ? Number(e.target.value) : null)}>
                <option value="">— not linked —</option>
                {nodes
                  .filter((n) => !["tower", "wing", "floor", "basement", "flat"].includes(n.kind))
                  .map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.name}
                    </option>
                  ))}
              </select>
            </Field>
            <Button size="small" onClick={() => setLinkFor(null)}>
              Close
            </Button>
          </div>
        )}
        {!compact && (
          <ul className="xray-legend" aria-label="Status">
            {legend.map((l) => (
              <li key={l.label} className="legend-item">
                <i className="swatch" style={l.outline ? { border: `2px solid ${l.color}`, background: "transparent" } : { background: l.color }} />
                {l.label} {l.count}
              </li>
            ))}
          </ul>
        )}
        {!compact && (
          <div className="xray-progress">
            <span>Overall progress</span>
            <b>{Math.round(site.progress)}%</b>
            {next && <span>Next: {next}</span>}
          </div>
        )}
      </div>
      {!compact && !bare && span > 0 && (
        <div className="xray-time">
          <Button className="xray-play" onClick={() => (day >= span ? (setDay(0), setPlaying(true)) : setPlaying(!playing))} aria-label={playing ? "Pause the replay" : "Play the replay"}>
            {playing ? <span aria-hidden="true">❚❚</span> : <Icon name="play" size={16} />}
          </Button>
          <label className="xray-slider">
            <span>Progress on a date</span>
            <input type="range" min={0} max={span} value={Math.min(day, span)} onChange={(e) => (setPlaying(false), setDay(Number(e.target.value)))} />
          </label>
          <b className="xray-date">{on >= now ? "Today" : new Date(`${on}T12:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</b>
          {!portal && (
            <Button onClick={saveVideo} disabled={recording} title="The replay as a short video (WebM, at most 30 s)">
              {recording ? "Recording…" : "Save video for client"}
            </Button>
          )}
        </div>
      )}
      {showsSectionLine(portal, compact) && !bare && (
        <p className="xray-note muted small">
          {building.levels.source === "section" ? building.levels.note : `Heights: the defaults (${building.settings.floor_height_m} m floor to floor) — ${building.levels.note ?? "no levels on the drawing"}`}
        </p>
      )}
    </div>
  );
}
