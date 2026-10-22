// A still picture of the building, rendered off screen (no canvas on the page): the dashboard's
// tiles and the work completion certificate's 3D page.
import type { NodeStatus } from "../pages/site/three/colors";
import type { Building, TimelineRow } from "./geometry";
import { statusAt } from "./geometry";
import type { Mode, RoomState } from "./scene";
import { XrayScene } from "./scene";

export type PictureModel = { building: Building | null; nodes: { id: number; status: NodeStatus; timeline?: TimelineRow[] }[] };

export async function renderPicture(model: PictureModel, mode: Mode, width: number, height: number): Promise<HTMLCanvasElement | null> {
  if (!model.building) return null;
  const canvas = document.createElement("canvas");
  Object.defineProperty(canvas, "clientWidth", { value: width });
  Object.defineProperty(canvas, "clientHeight", { value: height });
  const s = new XrayScene(canvas, model.building, { mode, bloom: false });
  s.renderer.setPixelRatio(1);
  s.resize();
  const today = new Date().toISOString().slice(0, 10);
  const states = new Map<number, RoomState>();
  const byId = new Map(model.nodes.map((n) => [n.id, n]));
  for (const r of model.building.rooms) {
    const n = byId.get(r.node_id);
    if (n) states.set(r.node_id, statusAt(n.timeline ?? [], today, today, n.status));
  }
  s.setStates(states);
  await new Promise((r) => setTimeout(r, 300));
  const out = document.createElement("canvas");
  out.width = canvas.width;
  out.height = canvas.height;
  out.getContext("2d")!.drawImage(canvas, 0, 0);
  s.dispose();
  return out;
}
