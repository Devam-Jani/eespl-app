// Loading a site's IFC file in the browser: web-ifc and its WebAssembly are fetched only when
// someone opens the BIM view (this module is its own chunk), single-threaded (no special headers).
import { fetchObjectUrl } from "../api";
import type { IfcElement } from "./ifc";
import { parseIfc } from "./ifc";

export async function loadIfc(url: string, headers?: Record<string, string>): Promise<IfcElement[]> {
  const [{ IfcAPI }, wasm] = await Promise.all([import("web-ifc"), import("web-ifc/web-ifc.wasm?url")]);
  const blobUrl = await fetchObjectUrl(url, true, headers);
  if (!blobUrl) throw new Error("The IFC file could not be fetched.");
  const bytes = new Uint8Array(await (await fetch(blobUrl)).arrayBuffer());
  URL.revokeObjectURL(blobUrl);
  const api = new IfcAPI();
  await api.Init(() => wasm.default, true);
  return parseIfc(api, bytes);
}
