import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

/** What a map shows. Tiles come from the settings (OpenStreetMap by default, no key), with the
 * credit shown; pins are drawn as HTML (numbered), so no marker images are fetched. */
export type MapPin = { lat: number; lng: number; label?: string; title?: string; kind?: "stop" | "home" | "site" | "person" | "flag" | "start"; popup?: string };
export type MapLine = { points: [number, number][]; color?: string; dashed?: boolean; weight?: number };
export type MapCircle = { lat: number; lng: number; radius: number; color?: string };

export default function MapView({
  tileUrl,
  attribution,
  pins = [],
  lines = [],
  circles = [],
  height = 420,
  onPick,
  picked,
}: {
  tileUrl: string;
  attribution: string;
  pins?: MapPin[];
  lines?: MapLine[];
  circles?: MapCircle[];
  height?: number | string;
  /** click on the map to pick a place (a site's pin, a home) */
  onPick?: (lat: number, lng: number) => void;
  picked?: [number, number] | null;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const pick = useRef(onPick);
  pick.current = onPick;

  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { zoomControl: true, attributionControl: true }).setView([23.03, 72.55], 11);
    L.tileLayer(tileUrl, { attribution, maxZoom: 19 }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => pick.current?.(Number(e.latlng.lat.toFixed(6)), Number(e.latlng.lng.toFixed(6))));
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, [tileUrl, attribution]);

  useEffect(() => {
    const m = map.current;
    const g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const bounds = L.latLngBounds([]);
    for (const c of circles) {
      L.circle([c.lat, c.lng], { radius: c.radius, color: c.color ?? "#2f6f4f", weight: 1, fillOpacity: 0.08 }).addTo(g);
      bounds.extend(L.latLng(c.lat, c.lng).toBounds(c.radius * 2));
    }
    for (const line of lines) {
      if (line.points.length < 2) continue;
      L.polyline(line.points, { color: line.color ?? "#1f6feb", weight: line.weight ?? 4, opacity: 0.85, dashArray: line.dashed ? "6 8" : undefined }).addTo(g);
      line.points.forEach((p) => bounds.extend(p));
    }
    for (const p of pins) {
      const icon = L.divIcon({ className: `map-pin map-pin-${p.kind ?? "stop"}`, html: `<span>${escapeHtml(p.label ?? "")}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] });
      const mk = L.marker([p.lat, p.lng], { icon, title: p.title }).addTo(g);
      if (p.popup) mk.bindPopup(p.popup);
      bounds.extend([p.lat, p.lng]);
    }
    if (picked) {
      L.marker(picked, { icon: L.divIcon({ className: "map-pin map-pin-picked", html: "<span>●</span>", iconSize: [26, 26], iconAnchor: [13, 13] }) }).addTo(g);
      bounds.extend(picked);
    }
    if (bounds.isValid()) m.fitBounds(bounds, { padding: [28, 28], maxZoom: 17 });
  }, [pins, lines, circles, picked]);

  return <div ref={el} className="field-map" style={{ height }} />;
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}
