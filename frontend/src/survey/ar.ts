// AR measure (WebXR immersive-ar with hit-test: Chrome on an ARCore Android phone). The user taps
// the corners of the area on the detected floor; the polygon closes on "Done" and each side and
// the area show live. Then the wall height: tap the floor-wall line, then the top of the wall
// (when the phone finds vertical surfaces), else it is typed in.
import * as THREE from "three";

export type ArResult = { polygon: [number, number][]; wallHeight: number | null };
type XRNav = { xr?: { isSessionSupported: (mode: string) => Promise<boolean>; requestSession: (mode: string, init: object) => Promise<XRSessionLike> } };
type XRSessionLike = EventTarget & {
  requestReferenceSpace: (t: string) => Promise<unknown>;
  requestHitTestSource?: (o: { space: unknown }) => Promise<{ cancel: () => void }>;
  end: () => Promise<void>;
};

/** Why AR is not available here (null: it is). */
export async function arUnavailable(): Promise<string | null> {
  const xr = (navigator as unknown as XRNav).xr;
  if (!window.isSecureContext) return "AR measure needs the app over HTTPS.";
  if (!xr) return "AR measure needs Chrome on an ARCore Android phone (not available on iPhone or desktop).";
  try {
    return (await xr.isSessionSupported("immersive-ar")) ? null : "This phone or browser has no WebXR AR: use the marker photo or the laser.";
  } catch {
    return "This browser blocks WebXR AR: use the marker photo or the laser.";
  }
}

export function sideLengths(pts: [number, number][]): number[] {
  return pts.map((a, i) => {
    const b = pts[(i + 1) % pts.length];
    return Math.hypot(b[0] - a[0], b[1] - a[1]);
  });
}

export function area(pts: [number, number][]): number {
  let s = 0;
  pts.forEach((a, i) => {
    const b = pts[(i + 1) % pts.length];
    s += a[0] * b[1] - b[0] * a[1];
  });
  return Math.abs(s) / 2;
}

/** Run the AR session in `overlay` (dom-overlay root with the buttons and the readout). */
export async function measure(
  overlay: HTMLElement,
  ui: { status: (text: string) => void; readout: (sides: number[], areaSqm: number | null) => void; done: Promise<"floor" | "wall" | "cancel">; wallDone: Promise<number | null> },
): Promise<ArResult | null> {
  const xr = (navigator as unknown as XRNav).xr!;
  const session = await xr.requestSession("immersive-ar", { requiredFeatures: ["hit-test"], optionalFeatures: ["dom-overlay"], domOverlay: { root: overlay } });
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.xr.enabled = true;
  renderer.xr.setReferenceSpaceType("local");
  document.body.appendChild(renderer.domElement);
  await renderer.xr.setSession(session as unknown as XRSession);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2));
  const reticle = new THREE.Mesh(new THREE.RingGeometry(0.04, 0.055, 32).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0x009e73 }));
  reticle.matrixAutoUpdate = false;
  reticle.visible = false;
  scene.add(reticle);
  const lineMat = new THREE.LineBasicMaterial({ color: 0xe69f00 });
  const points: THREE.Vector3[] = [];
  let line: THREE.Line | null = null;
  let phase: "floor" | "wall" = "floor";
  const wallPts: THREE.Vector3[] = [];
  const viewer = await session.requestReferenceSpace("viewer");
  const source = await session.requestHitTestSource!({ space: viewer });
  const redraw = () => {
    if (line) scene.remove(line);
    if (points.length > 1) {
      const g = new THREE.BufferGeometry().setFromPoints([...points, points[0]]);
      line = new THREE.Line(g, lineMat);
      scene.add(line);
    }
    const flat = points.map((p) => [p.x, p.z] as [number, number]);
    ui.readout(sideLengths(flat).slice(0, Math.max(0, flat.length - (flat.length > 2 ? 0 : 1))), flat.length > 2 ? area(flat) : null);
  };
  const onSelect = () => {
    if (!reticle.visible) return;
    const p = new THREE.Vector3().setFromMatrixPosition(reticle.matrix);
    if (phase === "floor") {
      points.push(p);
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.02), new THREE.MeshBasicMaterial({ color: 0xd55e00 }));
      dot.position.copy(p);
      scene.add(dot);
      redraw();
      ui.status(points.length < 3 ? `Corner ${points.length} set: tap the next corner` : "Tap more corners, or Done to close the outline");
    } else if (wallPts.length < 2) {
      wallPts.push(p);
      ui.status(wallPts.length === 1 ? "Now tap the top of the wall" : `Wall height ${Math.abs(wallPts[1].y - wallPts[0].y).toFixed(2)} m`);
    }
  };
  session.addEventListener("select", onSelect);
  renderer.setAnimationLoop((_t, frame) => {
    if (!frame) return;
    const ref = renderer.xr.getReferenceSpace();
    const hits = (frame as unknown as { getHitTestResults: (s: unknown) => { getPose: (r: unknown) => { transform: { matrix: Float32Array } } | null }[] }).getHitTestResults(
      source,
    );
    if (hits.length && ref) {
      const pose = hits[0].getPose(ref);
      if (pose) {
        reticle.visible = true;
        reticle.matrix.fromArray(pose.transform.matrix);
      }
    } else reticle.visible = false;
    renderer.render(scene, camera);
  });
  ui.status("Point at the floor until the green ring shows, then tap each corner of the area");
  const finished = await ui.done;
  let result: ArResult | null = null;
  if (finished !== "cancel" && points.length >= 3) {
    let wall: number | null = null;
    if (finished === "wall") {
      phase = "wall";
      ui.status("Tap where the wall meets the floor, then the top of the wall (or type the height)");
      const typed = await ui.wallDone;
      wall = wallPts.length === 2 ? Math.abs(wallPts[1].y - wallPts[0].y) : typed;
    }
    const origin = points[0];
    result = { polygon: points.map((p) => [round(p.x - origin.x), round(p.z - origin.z)]), wallHeight: wall };
  }
  source.cancel();
  renderer.setAnimationLoop(null);
  await session.end().catch(() => undefined);
  renderer.domElement.remove();
  renderer.dispose();
  return result;
}

function round(v: number): number {
  return Math.round(v * 1000) / 1000;
}

/** A plan drawing of the AR outline (saved as the overlay image: WebXR gives no camera frame). */
export function planImage(polygon: [number, number][], label: string): Promise<Blob | null> {
  const c = document.createElement("canvas");
  c.width = 1200;
  c.height = 900;
  const g = c.getContext("2d")!;
  g.fillStyle = "#fff";
  g.fillRect(0, 0, c.width, c.height);
  const xs = polygon.map((p) => p[0]);
  const ys = polygon.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = Math.min(1000 / Math.max(0.1, maxX - minX), 700 / Math.max(0.1, maxY - minY));
  const P = (p: [number, number]) => [100 + (p[0] - minX) * scale, 120 + (p[1] - minY) * scale] as const;
  g.strokeStyle = "#E69F00";
  g.lineWidth = 6;
  g.beginPath();
  polygon.forEach((p, i) => (i ? g.lineTo(...P(p)) : g.moveTo(...P(p))));
  g.closePath();
  g.stroke();
  g.fillStyle = "#111";
  g.font = "28px sans-serif";
  sideLengths(polygon).forEach((s, i) => {
    const a = P(polygon[i]);
    const b = P(polygon[(i + 1) % polygon.length]);
    g.fillText(`${s.toFixed(2)} m`, (a[0] + b[0]) / 2 + 8, (a[1] + b[1]) / 2 - 8);
  });
  g.font = "bold 32px sans-serif";
  g.fillText(`${label}: ${area(polygon).toFixed(2)} sqm (AR measure)`, 40, 60);
  return new Promise((resolve) => c.toBlob((b) => resolve(b), "image/png"));
}
