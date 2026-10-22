// The director's dashboard: a small X-ray tile per active site with a building model, each a still
// picture rendered off screen one after another (one WebGL context at a time, however many
// sites), redrawn when its model changes (its ETag), opening the full 3D view.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import type { Building, TimelineRow } from "./geometry";
import type { NodeStatus } from "../pages/site/three/colors";
import { renderPicture } from "./picture";

type Row = { site_id: number; code: string; name: string; version: number; progress: number };
type Model = { version: string; building: Building | null; nodes: { id: number; status: NodeStatus; timeline?: TimelineRow[] }[] };
const POLL_MS = 120_000;

async function picture(model: Model): Promise<string | null> {
  const c = await renderPicture(model, "xray", 520, 340);
  return c ? c.toDataURL("image/png") : null;
}

export default function XrayTiles() {
  const [rows, setRows] = useState<Row[]>([]);
  const [pics, setPics] = useState<Record<number, string>>({});
  useEffect(() => {
    let alive = true;
    const tags: Record<number, string> = {};
    async function refresh() {
      const list = await api<Row[]>("/api/building/active-sites").catch(() => [] as Row[]);
      if (!alive) return;
      setRows(list);
      for (const r of list) {
        try {
          const m = await api<Model>(`/api/sites/${r.site_id}/model`, tags[r.site_id] ? { headers: { "If-None-Match": `"${tags[r.site_id]}"` } } : {});
          tags[r.site_id] = m.version;
          const url = await picture(m);
          if (alive && url) setPics((p) => ({ ...p, [r.site_id]: url }));
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 304)) continue;
        }
      }
    }
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  if (!rows.length) return null;
  return (
    <section className="dash-section">
      <h2 className="section-title">Sites in 3D</h2>
      <div className="xray-tiles">
        {rows.map((r) => (
          <Link key={r.site_id} className="xray-tile" to={`/sites/${r.site_id}?tab=3d`}>
            {pics[r.site_id] ? <img src={pics[r.site_id]} alt={`${r.name} in 3D`} /> : <img alt="" />}
            <div>
              <b>{r.code}</b> {r.name} · {Math.round(r.progress)}%
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
