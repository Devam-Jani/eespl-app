import { useEffect, useState } from "react";
import { fetchObjectUrl } from "../api";

export type MapSettings = {
  tile_url: string;
  tile_attribution: string;
  point_every_s: number;
  point_move_m: number;
  accuracy_max_m: number;
  site_radius_m: number;
  auto_end_at: string;
  home_flag_m: number;
};
export type Flag = { code: string; text: string; stop?: number };
export type Leg = { from: string; to: string; km: number; minutes: number | null; estimated: boolean };
export type Stop = {
  id: number;
  seq: number;
  kind: string;
  site_id: number | null;
  name: string;
  note: string | null;
  in_at: string;
  out_at: string | null;
  minutes: number | null;
  in_outside: boolean;
  in_distance_m: number | null;
  in_reason: string | null;
  out_outside: boolean;
  out_distance_m: number | null;
  out_reason: string | null;
  has_selfie: boolean;
  has_out_selfie: boolean;
  in_lat: number;
  in_lng: number;
};
export type Day = {
  id: number;
  user_id: string;
  person: string;
  on_date: string;
  started_at: string;
  ended_at: string | null;
  auto_ended: boolean;
  start: [number, number] | null;
  start_home_m: number | null;
  end: [number, number] | null;
  end_home_m: number | null;
  legs: Leg[];
  route_km: number | null;
  route_estimated: boolean;
  tracked_km: number | null;
  km_basis: "route" | "tracked";
  km_basis_reason: string | null;
  km: number;
  flags: Flag[];
  points_total: number;
  points_good: number;
  points_deleted: boolean;
  stops: Stop[];
  points?: [number, number, string, number | null, boolean][];
  home?: [number, number] | null;
  road?: [number, number][] | null;
  settings?: MapSettings;
  can_choose_basis?: boolean;
};
export type MySite = { id: number; code: string; name: string; lat: number | null; lng: number | null; radius_m: number; maps_link: string | null };

export const STOP_KINDS: [string, string][] = [
  ["site", "Site"],
  ["vendor", "Vendor"],
  ["godown", "Godown"],
  ["client_office", "Client office"],
  ["other", "Other"],
];

export type Fix = { lat: number; lng: number; accuracy: number };

/** The phone's location now (high accuracy), or a plain message. */
export function locate(): Promise<Fix> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("This browser cannot give your location"));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: Number(p.coords.latitude.toFixed(6)), lng: Number(p.coords.longitude.toFixed(6)), accuracy: Math.round(p.coords.accuracy) }),
      (e) => reject(new Error(e.code === 1 ? "Location is blocked: allow location for this site in the browser" : "Could not get your location; try again in the open")),
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 10000 },
    );
  });
}

export function time(at: string | null | undefined): string {
  if (!at) return "—";
  return new Date(at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}

export function dist(m: number | null | undefined): string {
  if (m === null || m === undefined) return "—";
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

export function km(v: number | string | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "—" : `${Number(v).toFixed(digits)} km`;
}

/** A photo behind the login (a selfie, a bill), fetched with the token. */
export function AuthImage({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    let made: string | null = null;
    void fetchObjectUrl(path).then((u) => {
      made = u;
      if (!gone) setUrl(u);
    });
    return () => {
      gone = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [path]);
  return url ? <img src={url} alt={alt} className={className ?? "field-thumb"} /> : <span className="muted small">…</span>;
}

export function Flags({ flags }: { flags: Flag[] }) {
  if (!flags.length) return <span className="muted small">no flags</span>;
  return (
    <ul className="field-flags">
      {flags.map((f, i) => (
        <li key={i} className="text-danger small">
          ⚑ {f.text}
        </li>
      ))}
    </ul>
  );
}
