import { useEffect, useRef } from "react";

/** Draw a signature with a finger or the mouse; reports a PNG data URL (or null when cleared). */
export default function SignaturePad({ onChange }: { onChange: (dataUrl: string | null) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const drawn = useRef(false);

  useEffect(() => {
    const c = canvas.current!;
    const ratio = window.devicePixelRatio || 1;
    c.width = c.clientWidth * ratio;
    c.height = c.clientHeight * ratio;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.strokeStyle = "#14231c";
  }, []);

  const point = (e: React.PointerEvent) => {
    const r = canvas.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top] as const;
  };

  function down(e: React.PointerEvent) {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    canvas.current!.setPointerCapture(e.pointerId);
    drawing.current = true;
    ctx.beginPath();
    ctx.moveTo(...point(e));
  }

  function move(e: React.PointerEvent) {
    const ctx = canvas.current?.getContext("2d");
    if (!drawing.current || !ctx) return;
    ctx.lineTo(...point(e));
    ctx.stroke();
    drawn.current = true;
  }

  function up() {
    if (!drawing.current) return;
    drawing.current = false;
    if (drawn.current) onChange(canvas.current!.toDataURL("image/png"));
  }

  function clear() {
    const c = canvas.current!;
    c.getContext("2d")?.clearRect(0, 0, c.width, c.height);
    drawn.current = false;
    onChange(null);
  }

  return (
    <div className="signature">
      <canvas ref={canvas} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={up} aria-label="Signature pad" />
      <button type="button" className="btn btn-small" onClick={clear}>
        Clear
      </button>
    </div>
  );
}
