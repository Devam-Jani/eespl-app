// The measuring camera: the app's own camera screen (never the gallery) for survey photos.
// Rear camera at the highest resolution offered, zoom held at 1x where the phone lets us, guides
// (thirds, centre cross, tilt), torch, and a blur / brightness check before anything is saved.
//   Marker photo: two printed 150 mm markers on the surface; tap the corners on the photo.
//   AR measure:   WebXR on ARCore Android phones; tap the corners on the floor.
//   Laser / hand: the photo is proof only; the size is typed in the area form.
import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { api } from "../api";
import { errorText } from "../format";
import { arUnavailable, measure as arMeasure, planImage } from "./ar";
import { calibrate, detectMarkers, lengthM, liveReach, measure as markerMeasure, TOO_BIG } from "./marker";
import type { Calibration, Detected, Measurement, Pt } from "./marker";
import { verdict } from "./quality";
import type { Quality } from "./quality";
import type { Area, Survey } from "./SurveyPages";

type Mode = "marker" | "ar" | "photo";
type Shot = { blob: Blob; width: number; height: number; work: ImageData; url: string; quality: Quality };
const WORK_LONG_SIDE = 1600;

export default function Camera({ area, onClose, onSaved }: { area: Area; onClose: () => void; onSaved: (s: Survey) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [mode, setMode] = useState<Mode>("marker");
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [torch, setTorch] = useState<boolean | null>(null); // null: no torch on this camera
  const [dark, setDark] = useState(false);
  const [tilt, setTilt] = useState<{ beta: number; gamma: number } | null>(null);
  const [needsTiltPermission, setNeedsTiltPermission] = useState(false);
  const [live, setLive] = useState<Detected[]>([]);
  const [shot, setShot] = useState<Shot | null>(null);
  // where the picture sits inside the letterboxed video element (for the live outlines)
  const [box, setBox] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  useEffect(() => {
    const fit = () => {
      const v = video.current;
      if (!v || !v.videoWidth) return;
      const r = v.getBoundingClientRect();
      const scale = Math.min(r.width / v.videoWidth, r.height / v.videoHeight);
      const width = v.videoWidth * scale;
      const height = v.videoHeight * scale;
      setBox({ left: (r.width - width) / 2, top: (r.height - height) / 2, width, height });
    };
    const v = video.current;
    v?.addEventListener("loadedmetadata", fit);
    window.addEventListener("resize", fit);
    const t = setInterval(fit, 1000);
    return () => {
      v?.removeEventListener("loadedmetadata", fit);
      window.removeEventListener("resize", fit);
      clearInterval(t);
    };
  }, [shot]);
  const [busy, setBusy] = useState(false);
  const [arReason, setArReason] = useState<string | null>("checking…");
  const worker = useRef<Worker | null>(null);

  // --- camera ---
  useEffect(() => {
    let stopped = false;
    void (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: "environment" }, width: { ideal: 4096 }, height: { ideal: 3072 } },
        });
        if (stopped) return s.getTracks().forEach((t) => t.stop());
        stream.current = s;
        if (video.current) {
          video.current.srcObject = s;
          await video.current.play().catch(() => undefined);
        }
        const track = s.getVideoTracks()[0];
        const caps = (track.getCapabilities?.() ?? {}) as MediaTrackCapabilities & { zoom?: { min: number; max: number }; torch?: boolean };
        const msgs: string[] = [];
        if (caps.zoom) {
          const want = Math.max(caps.zoom.min, Math.min(1, caps.zoom.max));
          try {
            await track.applyConstraints({ advanced: [{ zoom: want } as MediaTrackConstraintSet] });
          } catch {
            msgs.push("Keep the zoom at 1x");
          }
          if (want !== 1) msgs.push("Keep the zoom at 1x");
        } else msgs.push("Keep the zoom at 1x (this camera does not let the app set it)");
        if (caps.torch) setTorch(false);
        setNotes(msgs);
      } catch (err) {
        setError(`The camera did not start: ${errorText(err)}. Allow camera access for this site.`);
      }
    })();
    return () => {
      stopped = true;
      stream.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  useEffect(() => {
    void arUnavailable().then(setArReason);
    worker.current = new Worker(new URL("./quality.worker.ts", import.meta.url), { type: "module" });
    return () => worker.current?.terminate();
  }, []);

  // --- tilt (DeviceOrientation; iOS asks first) ---
  useEffect(() => {
    const D = window.DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> } | undefined;
    if (D && typeof D.requestPermission === "function") setNeedsTiltPermission(true);
    const on = (e: DeviceOrientationEvent) => e.beta !== null && setTilt({ beta: e.beta, gamma: e.gamma ?? 0 });
    window.addEventListener("deviceorientation", on);
    return () => window.removeEventListener("deviceorientation", on);
  }, []);
  const wall = /wall/i.test(area.area_type ?? "");
  const tiltOk = tilt ? (wall ? Math.abs(tilt.beta - 90) <= 5 && Math.abs(tilt.gamma) <= 5 : tilt.beta >= 30 && tilt.beta <= 60) : null;

  // --- live checks on a small frame: darkness, and the markers in marker mode ---
  useEffect(() => {
    if (shot) return;
    const c = document.createElement("canvas");
    const t = setInterval(() => {
      const v = video.current;
      if (!v || !v.videoWidth) return;
      const w = Math.min(800, v.videoWidth); // the markers need ~80 px to be read
      const h = Math.round((v.videoHeight / v.videoWidth) * w);
      c.width = w;
      c.height = h;
      const g = c.getContext("2d", { willReadFrequently: true })!;
      g.drawImage(v, 0, 0, w, h);
      const img = g.getImageData(0, 0, w, h);
      let sum = 0;
      for (let i = 0; i < img.data.length; i += 16) sum += img.data[i];
      setDark(sum / (img.data.length / 16) < 60);
      if (mode === "marker") void detectMarkers(img).then((found) => setLive(found.map((m) => ({ id: m.id, corners: m.corners.map((p) => ({ x: p.x / w, y: p.y / h })) }))));
    }, 700);
    return () => clearInterval(t);
  }, [mode, shot]);

  async function toggleTorch() {
    const track = stream.current?.getVideoTracks()[0];
    if (!track || torch === null) return;
    try {
      await track.applyConstraints({ advanced: [{ torch: !torch } as MediaTrackConstraintSet] });
      setTorch(!torch);
    } catch {
      setTorch(null);
    }
  }

  // --- take the still ---
  const take = useCallback(async () => {
    const v = video.current;
    const track = stream.current?.getVideoTracks()[0];
    if (!v || !track) return;
    setBusy(true);
    setError(null);
    try {
      let blob: Blob | null = null;
      const IC = (
        window as unknown as {
          ImageCapture?: new (t: MediaStreamTrack) => {
            getPhotoCapabilities: () => Promise<{ imageWidth?: { max: number }; imageHeight?: { max: number } }>;
            takePhoto: (s?: object) => Promise<Blob>;
          };
        }
      ).ImageCapture;
      if (IC) {
        try {
          const ic = new IC(track);
          const caps = await ic.getPhotoCapabilities();
          blob = await ic.takePhoto({ imageWidth: caps.imageWidth?.max, imageHeight: caps.imageHeight?.max });
        } catch {
          blob = null;
        }
      }
      if (!blob) {
        const c = document.createElement("canvas");
        c.width = v.videoWidth;
        c.height = v.videoHeight;
        c.getContext("2d")!.drawImage(v, 0, 0);
        blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.92));
      }
      if (!blob) throw new Error("no image");
      const bmp = await createImageBitmap(blob);
      const scale = Math.min(1, WORK_LONG_SIDE / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas");
      c.width = Math.round(bmp.width * scale);
      c.height = Math.round(bmp.height * scale);
      const g = c.getContext("2d", { willReadFrequently: true })!;
      g.drawImage(bmp, 0, 0, c.width, c.height);
      const work = g.getImageData(0, 0, c.width, c.height);
      // blur / brightness on a 640 px copy, in the worker
      const small = document.createElement("canvas");
      small.width = 640;
      small.height = Math.round((c.height / c.width) * 640);
      const sg = small.getContext("2d", { willReadFrequently: true })!;
      sg.drawImage(c, 0, 0, small.width, small.height);
      const sd = sg.getImageData(0, 0, small.width, small.height);
      const q = await new Promise<Quality>((resolve) => {
        worker.current!.onmessage = (e: MessageEvent<Quality>) => resolve(e.data);
        worker.current!.postMessage({ data: sd.data, width: sd.width, height: sd.height });
      });
      const why = verdict(q);
      if (why) {
        setError(why);
        return;
      }
      setShot({ blob, width: bmp.width, height: bmp.height, work, url: c.toDataURL("image/jpeg", 0.9), quality: q });
    } catch (err) {
      setError(`Could not take the photo: ${errorText(err)}`);
    } finally {
      setBusy(false);
    }
  }, []);

  // --- AR ---
  const overlayRef = useRef<HTMLDivElement>(null);
  const [arStatus, setArStatus] = useState<string>("");
  const [arRead, setArRead] = useState<{ sides: number[]; area: number | null }>({ sides: [], area: null });
  const arDone = useRef<(v: "floor" | "wall" | "cancel") => void>(() => undefined);
  const wallDone = useRef<(v: number | null) => void>(() => undefined);
  const [arWallTyped, setArWallTyped] = useState("");
  const [arActive, setArActive] = useState(false);
  async function startAr() {
    if (!overlayRef.current) return;
    setArActive(true);
    try {
      const result = await arMeasure(overlayRef.current, {
        status: setArStatus,
        readout: (sides, a) => setArRead({ sides, area: a }),
        done: new Promise((r) => (arDone.current = r)),
        wallDone: new Promise((r) => (wallDone.current = r)),
      });
      setArActive(false);
      if (!result) return;
      const plan = await planImage(result.polygon, area.name);
      setBusy(true);
      const next = await upload(plan!, plan, { mode: "ar", width_px: "1200", height_px: "900" });
      onSaved(
        await api<Survey>(`/api/surveys/areas/${area.id}/camera`, {
          method: "POST",
          json: { method: "ar", polygon_m: result.polygon, wall_height_m: result.wallHeight, accuracy_note: "AR measure (WebXR hit-test)" },
        }).catch(() => next),
      );
    } catch (err) {
      setArActive(false);
      setError(`AR stopped: ${errorText(err)}`);
    } finally {
      setBusy(false);
    }
  }

  // --- save ---
  async function meta(extra: Record<string, string>): Promise<FormData> {
    const form = new FormData();
    form.append("taken_at", new Date().toISOString());
    const track = stream.current?.getVideoTracks()[0];
    const settings = (track?.getSettings?.() ?? {}) as MediaTrackSettings & { zoom?: number };
    if (settings.zoom) form.append("zoom", String(settings.zoom));
    if (tilt) {
      form.append("tilt_beta", tilt.beta.toFixed(1));
      form.append("tilt_gamma", tilt.gamma.toFixed(1));
    }
    form.append("browser", navigator.userAgent.slice(0, 300));
    const uad = (navigator as unknown as { userAgentData?: { getHighEntropyValues: (k: string[]) => Promise<{ model?: string; platform?: string }> } }).userAgentData;
    if (uad) {
      try {
        const hv = await uad.getHighEntropyValues(["model", "platform"]);
        form.append("device", [hv.platform, hv.model].filter(Boolean).join(" ").slice(0, 200));
      } catch {
        // not shared
      }
    }
    const pos = await new Promise<GeolocationPosition | null>((r) => {
      if (!navigator.geolocation) return r(null);
      navigator.geolocation.getCurrentPosition(r, () => r(null), { timeout: 3000, maximumAge: 60000 });
    });
    if (pos) {
      form.append("lat", pos.coords.latitude.toFixed(7));
      form.append("lng", pos.coords.longitude.toFixed(7));
      form.append("gps_accuracy_m", pos.coords.accuracy.toFixed(1));
    }
    for (const [k, v] of Object.entries(extra)) form.append(k, v);
    return form;
  }
  async function upload(file: Blob, overlay: Blob | null, extra: Record<string, string>): Promise<Survey> {
    const form = await meta(extra);
    form.append("file", file, `area-${area.id}-${Date.now()}.${file.type === "image/png" ? "png" : "jpg"}`);
    if (overlay) form.append("overlay", overlay, `area-${area.id}-${Date.now()}-measured.png`);
    return api<Survey>(`/api/surveys/areas/${area.id}/photos`, { method: "POST", form });
  }
  async function saveProof() {
    if (!shot) return;
    setBusy(true);
    try {
      onSaved(
        await upload(shot.blob, null, {
          mode: area.method === "laser" ? "laser" : "manual",
          width_px: String(shot.width),
          height_px: String(shot.height),
          blur_score: shot.quality.sharpness.toFixed(2),
          brightness: shot.quality.brightness.toFixed(1),
        }),
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="camera-screen">
      {!shot && (
        <>
          <video ref={video} className="camera-video" playsInline muted autoPlay />
          <div className="camera-guides">
            <div className="grid-v" style={{ left: "33.33%" }} />
            <div className="grid-v" style={{ left: "66.66%" }} />
            <div className="grid-h" style={{ top: "33.33%" }} />
            <div className="grid-h" style={{ top: "66.66%" }} />
            <div className="cross" />
            {mode === "marker" && box && (
              <svg className="live-markers" viewBox="0 0 1 1" preserveAspectRatio="none" style={{ left: box.left, top: box.top, width: box.width, height: box.height }}>
                {live.map((m) => (
                  <polygon key={m.id} points={m.corners.map((p) => `${p.x},${p.y}`).join(" ")} />
                ))}
              </svg>
            )}
          </div>
          <div className="camera-top">
            <button className="btn btn-small" onClick={onClose}>
              ✕
            </button>
            <span className="camera-title">{area.name}</span>
            {torch !== null && (
              <button className={`btn btn-small ${dark && !torch ? "btn-primary" : ""}`} onClick={() => void toggleTorch()}>
                {torch ? "Torch off" : "Torch"}
              </button>
            )}
          </div>
          <div className="camera-status">
            {tilt ? (
              <span className={`tilt ${tiltOk ? "ok" : "bad"}`}>
                {wall ? `Wall: ${Math.round(tilt.beta)}° upright` : `Floor: ${Math.round(tilt.beta)}° down`} {tiltOk ? "✓" : wall ? "hold it upright" : "aim 30°–60° down"}
              </span>
            ) : needsTiltPermission ? (
              <button
                className="btn btn-small"
                onClick={() =>
                  void (window.DeviceOrientationEvent as unknown as { requestPermission: () => Promise<string> }).requestPermission().then(() => setNeedsTiltPermission(false))
                }
              >
                Show the tilt guide
              </button>
            ) : (
              <span className="tilt">No tilt sensor</span>
            )}
            {mode === "marker" && (
              <span className={`marker-state ${live.length >= 2 ? "ok" : ""}`}>
                {live.length >= 2 ? "2 markers found" : live.length === 1 ? "1 marker: both must show" : "Looking for the markers…"}
              </span>
            )}
            {mode === "marker" &&
              live.length >= 1 &&
              (() => {
                const r = liveReach(live);
                return r ? (
                  <span className="reach">
                    {r.set.name} markers: this photo can measure up to about {r.reachM.toFixed(1)} m across
                  </span>
                ) : null;
              })()}
            {dark && <span className="warn">Dark: {torch === null ? "move to the light" : "turn the torch on"}</span>}
            {notes.map((n) => (
              <span key={n} className="warn">
                {n}
              </span>
            ))}
          </div>
          {error && <div className="camera-error">{error}</div>}
          <div className="camera-bottom">
            <div className="mode-switch">
              {(["marker", "ar", "photo"] as Mode[])
                .filter((m) => m !== "ar" || arReason === null)
                .map((m) => (
                  <button key={m} className={`btn btn-small ${mode === m ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode(m)}>
                    {m === "marker" ? "Marker photo" : m === "ar" ? "AR measure" : "Laser / hand: proof photo"}
                  </button>
                ))}
            </div>
            {arReason && arReason !== "checking…" && <div className="small muted ar-why">AR measure hidden: {arReason}</div>}
            {mode === "ar" ? (
              <button className="shutter wide" disabled={busy} onClick={() => void startAr()}>
                Start AR
              </button>
            ) : (
              <button className="shutter" disabled={busy} aria-label="Take the photo" onClick={() => void take()} />
            )}
          </div>
        </>
      )}
      {shot && mode === "marker" && (
        <MarkerReview
          shot={shot}
          area={area}
          busy={busy}
          onRetake={() => setShot(null)}
          onSave={async (m, overlay, found) => {
            setBusy(true);
            try {
              await upload(shot.blob, overlay, {
                mode: "marker",
                marker_found: String(found),
                width_px: String(shot.width),
                height_px: String(shot.height),
                blur_score: shot.quality.sharpness.toFixed(2),
                brightness: shot.quality.brightness.toFixed(1),
              });
              onSaved(
                await api<Survey>(`/api/surveys/areas/${area.id}/camera`, {
                  method: "POST",
                  json: { method: "marker", polygon_m: m.polygonM, accuracy_note: `marker photo, the two markers agree within ${(m.spread * 100).toFixed(1)}%` },
                }),
              );
            } catch (err) {
              setError(errorText(err));
              setShot(null);
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
      {shot && mode === "photo" && (
        <div className="review">
          <img src={shot.url} alt="" className="review-img" />
          <div className="camera-bottom">
            <p className="small">Proof photo: the size is the laser / hand reading typed in the area.</p>
            <button className="btn" onClick={() => setShot(null)}>
              Retake
            </button>
            <button className="btn btn-primary" disabled={busy} onClick={() => void saveProof()}>
              Save photo
            </button>
          </div>
        </div>
      )}
      <div ref={overlayRef} className={`ar-overlay ${arActive ? "on" : ""}`}>
        {arActive && (
          <>
            <div className="ar-status">{arStatus}</div>
            <div className="ar-readout">
              {arRead.sides.map((s, i) => (
                <span key={i}>{s.toFixed(2)} m</span>
              ))}
              {arRead.area !== null && <b>{arRead.area.toFixed(2)} sqm</b>}
            </div>
            <div className="ar-buttons">
              <button className="btn" onClick={() => arDone.current("cancel")}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={() => arDone.current(wall ? "wall" : "floor")}>
                Done
              </button>
              {wall && (
                <span className="inline-form">
                  <input placeholder="or type the wall height, m" value={arWallTyped} onChange={(e) => setArWallTyped(e.target.value)} inputMode="decimal" />
                  <button className="btn btn-small" onClick={() => wallDone.current(arWallTyped ? Number(arWallTyped) : null)}>
                    Use
                  </button>
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Find the markers on the still, let the user tap the corners, show sides and area live. */
function MarkerReview({
  shot,
  area,
  busy,
  onRetake,
  onSave,
}: {
  shot: Shot;
  area: Area;
  busy: boolean;
  onRetake: () => void;
  onSave: (m: Measurement, overlay: Blob, found: boolean) => Promise<void>;
}) {
  const [cal, setCal] = useState<Calibration | null>(null);
  const [taps, setTaps] = useState<Pt[]>([]);
  const svg = useRef<SVGSVGElement>(null);
  const { width: W, height: H } = shot.work;
  useEffect(() => {
    void detectMarkers(shot.work).then((found) => setCal(calibrate(found, W)));
  }, [shot, W]);
  const m = cal?.ok && taps.length >= 3 ? markerMeasure(cal, taps) : null;
  const sideAt = (i: number): number | null => (cal?.ok && taps.length >= 2 ? lengthM(cal, taps[i], taps[(i + 1) % taps.length]) : null);
  function tap(e: ReactPointerEvent<SVGSVGElement>) {
    if (!cal?.ok || !svg.current) return;
    const pt = svg.current.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svg.current.getScreenCTM()!.inverse());
    setTaps([...taps, { x: p.x, y: p.y }]);
  }
  async function save() {
    if (!m || !cal?.ok) return;
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const g = c.getContext("2d")!;
    g.putImageData(shot.work, 0, 0);
    g.lineWidth = Math.max(3, W / 400);
    g.strokeStyle = "#009E73";
    for (const mk of cal.markers) {
      g.beginPath();
      mk.corners.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y)));
      g.closePath();
      g.stroke();
    }
    g.strokeStyle = "#E69F00";
    g.fillStyle = "rgba(230,159,0,0.18)";
    g.beginPath();
    taps.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y)));
    g.closePath();
    g.fill();
    g.stroke();
    g.font = `bold ${Math.round(W / 45)}px sans-serif`;
    g.fillStyle = "#111";
    g.strokeStyle = "#fff";
    g.lineWidth = 6;
    taps.forEach((p, i) => {
      const q = taps[(i + 1) % taps.length];
      const label = `${m.sidesM[i].toFixed(2)} m`;
      g.strokeText(label, (p.x + q.x) / 2, (p.y + q.y) / 2);
      g.fillText(label, (p.x + q.x) / 2, (p.y + q.y) / 2);
    });
    const head = `${area.name}: ${m.areaSqm.toFixed(2)} sqm (marker photo)`;
    g.strokeText(head, 20, Math.round(W / 30));
    g.fillText(head, 20, Math.round(W / 30));
    const blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/png"));
    if (blob) await onSave(m, blob, true);
  }
  return (
    <div className="review">
      <div className="review-stage">
        <img src={shot.url} alt="" className="review-img" />
        <svg ref={svg} className="review-svg" viewBox={`0 0 ${W} ${H}`} onPointerUp={tap}>
          {cal?.markers.map((mk) => (
            <polygon key={mk.id} className="mk" points={mk.corners.map((p) => `${p.x},${p.y}`).join(" ")} />
          ))}
          {taps.length > 1 && <polygon className="area-poly" points={taps.map((p) => `${p.x},${p.y}`).join(" ")} />}
          {taps.map((p, i) => (
            <g key={i}>
              <circle cx={p.x} cy={p.y} r={W / 120} className="tap" />
              {i < taps.length - 1 || taps.length >= 3
                ? (() => {
                    const q = taps[(i + 1) % taps.length];
                    const s = sideAt(i);
                    return s !== null && (i < taps.length - 1 || taps.length >= 3) ? (
                      <text x={(p.x + q.x) / 2} y={(p.y + q.y) / 2} className="side" fontSize={W / 40}>
                        {s.toFixed(2)} m
                      </text>
                    ) : null;
                  })()
                : null}
            </g>
          ))}
        </svg>
      </div>
      <div className="camera-bottom">
        {!cal && <p>Looking for the markers…</p>}
        {cal && !cal.ok && <p className="camera-error">{cal.reason}</p>}
        {cal?.ok && (
          <p className="small">
            {m ? (
              <>
                <b className="measured">
                  {m.areaSqm.toFixed(2)} sqm · {m.sidesM.map((s) => s.toFixed(2)).join(" × ")} m
                </b>
                {m.tooBig && (
                  <span className="too-big">
                    {TOO_BIG} The area is {m.extentM.toFixed(1)} m across; these {cal.set.name} markers allow about {m.reachM.toFixed(1)} m here.
                  </span>
                )}
              </>
            ) : (
              `Markers found. Tap the corners of the area in order (${taps.length} so far).`
            )}
          </p>
        )}
        <div className="inline-form">
          <button className="btn" onClick={onRetake}>
            Retake
          </button>
          {taps.length > 0 && (
            <button className="btn btn-ghost" onClick={() => setTaps(taps.slice(0, -1))}>
              Undo corner
            </button>
          )}
          <button className="btn btn-primary" disabled={!m || m.tooBig || busy} onClick={() => void save()}>
            Save measurement
          </button>
        </div>
      </div>
    </div>
  );
}
