/**
 * "Save image" for the 3D view: the WebGL picture composed on a white page with a header (site
 * name, code, date, overall %), the floor and tower labels with their %, and the colour legend
 * with counts. Layout helpers are pure (tested in three.test.ts); drawing needs a real canvas.
 */

export type SnapLabel = { text: string; x: number; y: number; tower: boolean; late: boolean }; // x, y: anchor in CSS px
export type SnapLegendItem = { label: string; color: string; count: number; ghost?: boolean; outline?: boolean };

export type SnapOptions = {
  siteName: string;
  siteCode: string;
  percent: number;
  date: Date;
  labels: SnapLabel[];
  legend: SnapLegendItem[];
  note?: string;
};

export function headerLines(o: Pick<SnapOptions, "siteName" | "siteCode" | "percent" | "date">): [string, string] {
  const day = o.date.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata",  day: "2-digit", month: "short", year: "numeric" });
  return [`${o.siteName} (${o.siteCode})`, `${day} · overall ${Math.round(o.percent)}% done`];
}

/** Greedy wrap: which items go on which row, given each item's width. */
export function wrapRows(widths: number[], maxWidth: number, gap: number): number[][] {
  const rows: number[][] = [];
  let row: number[] = [];
  let used = 0;
  widths.forEach((w, i) => {
    const need = row.length ? used + gap + w : w;
    if (row.length && need > maxWidth) {
      rows.push(row);
      row = [i];
      used = w;
    } else {
      row.push(i);
      used = need;
    }
  });
  if (row.length) rows.push(row);
  return rows;
}

export const legendText = (i: SnapLegendItem) => `${i.label} (${i.count})`;

/** Draw everything onto a new canvas, `scale` = device pixels per CSS pixel of the 3D canvas. */
export function composeSnapshot(source: HTMLCanvasElement, scale: number, o: SnapOptions): HTMLCanvasElement {
  const s = scale;
  const pad = 16 * s;
  const W = source.width;
  const headerH = 64 * s;
  const swatch = 12 * s;
  const font = (px: number, bold = false) => `${bold ? "600 " : ""}${px * s}px "DejaVu Sans", Arial, sans-serif`;

  const probe = document.createElement("canvas").getContext("2d")!;
  probe.font = font(12);
  const widths = o.legend.map((i) => swatch + 6 * s + probe.measureText(legendText(i)).width);
  const rows = wrapRows(widths, W - 2 * pad, 18 * s);
  const rowH = 20 * s;
  const legendH = pad + rows.length * rowH + (o.note ? rowH : 0) + pad / 2;

  const out = document.createElement("canvas");
  out.width = W;
  out.height = headerH + source.height + legendH;
  const ctx = out.getContext("2d")!;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, out.width, out.height);

  // header
  const [title, sub] = headerLines(o);
  ctx.fillStyle = "#14231c";
  ctx.font = font(18, true);
  ctx.textBaseline = "top";
  ctx.fillText(title, pad, 12 * s);
  ctx.font = font(13);
  ctx.fillStyle = "#4a5a52";
  ctx.fillText(sub, pad, 38 * s);
  ctx.fillStyle = "#2f6f4f";
  ctx.fillRect(0, headerH - 2 * s, W, 2 * s);

  // the 3D picture and its labels
  ctx.drawImage(source, 0, headerH);
  ctx.textBaseline = "bottom";
  for (const l of o.labels) {
    ctx.font = font(l.tower ? 13 : 11, l.tower || l.late);
    const tw = ctx.measureText(l.text).width;
    const x = l.x * s - tw / 2;
    const y = headerH + l.y * s;
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.fillRect(x - 4 * s, y - 16 * s, tw + 8 * s, 16 * s);
    ctx.fillStyle = l.late ? "#b00000" : "#14231c";
    ctx.fillText(l.text, x, y - 2 * s);
  }

  // legend
  ctx.textBaseline = "middle";
  ctx.font = font(12);
  let y = headerH + source.height + pad;
  for (const row of rows) {
    let x = pad;
    for (const i of row) {
      const item = o.legend[i];
      ctx.fillStyle = item.color;
      if (item.outline) {
        ctx.strokeStyle = item.color;
        ctx.lineWidth = 2 * s;
        ctx.strokeRect(x + s, y + s, swatch - 2 * s, swatch - 2 * s);
      } else {
        ctx.globalAlpha = item.ghost ? 0.5 : 1;
        ctx.fillRect(x, y, swatch, swatch);
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "#9aa3a0";
        ctx.lineWidth = s;
        ctx.strokeRect(x, y, swatch, swatch);
      }
      ctx.fillStyle = "#14231c";
      ctx.fillText(legendText(item), x + swatch + 6 * s, y + swatch / 2);
      x += widths[i] + 18 * s;
    }
    y += rowH;
  }
  if (o.note) {
    ctx.fillStyle = "#4a5a52";
    ctx.fillText(o.note, pad, y + swatch / 2);
  }
  return out;
}
