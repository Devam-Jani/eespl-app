// The measured areas in 3D: each outline sunk by its depth (a pool, a tank) or lifted by its rise
// (a slope), the one picked on the sheet lit up.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { ART, CHART, VIEWER } from "../ui/tokens";
import { bbox, flatten } from "./geom";
import type { Pt } from "./geom";

export type Area3D = { id: number; code: string; outline: Pt[]; depth_m: number; kind: string };

export function Measure3D({ areas, selected }: { areas: Area3D[]; selected: number | null }) {
  const host = useRef<HTMLDivElement>(null);
  const meshes = useRef<Map<number, THREE.Mesh>>(new Map());
  const draw = useRef<() => void>(() => undefined);

  useEffect(() => {
    const el = host.current;
    if (!el || !areas.length) return;
    const look = VIEWER.xray;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(look.bg);
    const w = el.clientWidth || 600;
    const h = el.clientHeight || 360;
    const camera = new THREE.PerspectiveCamera(40, w / h, 0.05, 2000);
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      el.textContent = "3D needs WebGL, which this browser has turned off.";
      return;
    }
    renderer.setSize(w, h);
    el.appendChild(renderer.domElement);
    scene.add(new THREE.AmbientLight(ART.camLight, 0.8));
    const sun = new THREE.DirectionalLight(ART.camLight, 0.9);
    sun.position.set(10, 20, 15);
    scene.add(sun);
    const all = areas.flatMap((a) => flatten(a.outline, 32));
    const [x1, y1, x2, y2] = bbox(all);
    const cx = (x1 + x2) / 2;
    const cy = (y1 + y2) / 2;
    const span = Math.max(x2 - x1, y2 - y1, 1);
    meshes.current.clear();
    areas.forEach((a, i) => {
      const pts = flatten(a.outline, 64).map(([x, y]) => new THREE.Vector2(x - cx, y - cy));
      const shape = new THREE.Shape(pts);
      const depth = Math.max(0.05, a.depth_m);
      const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false });
      const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(CHART[i % 6]), transparent: true, opacity: 0.55 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.y = a.kind === "slope" ? 0 : -depth; // a pool or tank goes down from the deck
      scene.add(mesh);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 20), new THREE.LineBasicMaterial({ color: new THREE.Color(look.line) }));
      edges.rotation.x = mesh.rotation.x;
      edges.position.y = mesh.position.y;
      scene.add(edges);
      meshes.current.set(a.id, mesh);
    });
    camera.position.set(span * 0.6, span * 0.7, span * 0.9);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, -0.5, 0);
    controls.update();
    let frame = 0;
    const render = () => renderer.render(scene, camera);
    draw.current = render;
    controls.addEventListener("change", () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(render);
    });
    render();
    return () => {
      cancelAnimationFrame(frame);
      controls.dispose();
      renderer.dispose();
      scene.traverse((o) => {
        if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) {
          o.geometry.dispose();
          (o.material as THREE.Material).dispose();
        }
      });
      el.innerHTML = "";
    };
  }, [areas]);

  useEffect(() => {
    meshes.current.forEach((m, id) => {
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.opacity = selected === null || id === selected ? 0.85 : 0.25;
      mat.emissive = new THREE.Color(id === selected ? VIEWER.xray.selected : ART.camDark);
      mat.emissiveIntensity = id === selected ? 0.25 : 0;
    });
    draw.current();
  }, [selected, areas]);

  return <div ref={host} className="measure-3d" role="img" aria-label="The measured areas in 3D" />;
}
