// A client's BIM (IFC) file in the 3D view, read in the browser with web-ifc (That Open Engine's
// core, pinned, its own lazy chunk). Every element with geometry becomes a mesh (positions placed
// by its transformation, metres, Y up); elements planning linked to our places take the place's
// status colour.
import type { FlatMesh, IfcAPI } from "web-ifc";
import type { Category } from "../pages/site/three/colors";
import { STATUS_COLORS } from "../pages/site/three/colors";

const IFCSPACE = 3856911033; // web-ifc's type code (the constant without loading the schema)

export type IfcElement = { expressID: number; type: string; name: string | null; positions: Float32Array; indices: Uint32Array; color: [number, number, number, number] };

/** The elements of an IFC file with their triangles (the vertex normals left out). */
export function parseIfc(api: IfcAPI, bytes: Uint8Array): IfcElement[] {
  const model = api.OpenModel(bytes, { COORDINATE_TO_ORIGIN: true });
  const out: IfcElement[] = [];
  try {
    const take = (mesh: FlatMesh) => {
      const line = api.GetLine(model, mesh.expressID);
      const type = (api.GetNameFromTypeCode(line?.type ?? 0) || "IFC").toUpperCase();
      const name: string | null = line?.Name?.value ?? line?.LongName?.value ?? null;
      const pos: number[] = [];
      const idx: number[] = [];
      let color: [number, number, number, number] = [0.8, 0.8, 0.8, 1];
      for (let g = 0; g < mesh.geometries.size(); g++) {
        const placed = mesh.geometries.get(g);
        color = [placed.color.x, placed.color.y, placed.color.z, placed.color.w];
        const geo = api.GetGeometry(model, placed.geometryExpressID);
        const verts = api.GetVertexArray(geo.GetVertexData(), geo.GetVertexDataSize());
        const index = api.GetIndexArray(geo.GetIndexData(), geo.GetIndexDataSize());
        const m = placed.flatTransformation; // 4 x 4, column-major
        const base = pos.length / 3;
        for (let i = 0; i < verts.length; i += 6) {
          const [x, y, z] = [verts[i], verts[i + 1], verts[i + 2]];
          pos.push(m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]);
        }
        for (const k of index) idx.push(base + k);
        geo.delete();
      }
      if (idx.length) out.push({ expressID: mesh.expressID, type, name, positions: new Float32Array(pos), indices: new Uint32Array(idx), color });
    };
    api.StreamAllMeshes(model, take);
    api.StreamAllMeshesWithTypes(model, [IFCSPACE], take); // the spaces (left out of the stream above): what planning links to our rooms
  } finally {
    api.CloseModel(model);
  }
  return out;
}

/** An element's colour: its linked place's status, else its own (greyed). */
export function ifcColor(el: IfcElement, links: Record<string, number>, states: Map<number, { category: Exclude<Category, "rollup"> }>): string | null {
  const node = links[String(el.expressID)];
  if (node == null) return null;
  const st = states.get(node);
  return STATUS_COLORS[st?.category ?? "not_started"];
}

/** Too big for an office laptop to open comfortably (the site's setting, 150 MB by default). */
export function tooBig(bytes: number, limitMb: number): boolean {
  return bytes > limitMb * 1024 * 1024;
}
