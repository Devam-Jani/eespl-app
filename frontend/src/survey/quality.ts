// Photo quality on a downscaled frame: brightness (mean 0..255) and sharpness (the variance of
// the Laplacian: low = blurred). Plain functions so the worker and the tests share them.

export type Quality = { brightness: number; sharpness: number };

export const MIN_BRIGHTNESS = 45;
export const MIN_SHARPNESS = 40;

export function quality(data: Uint8ClampedArray, width: number, height: number): Quality {
  const g = new Float32Array(width * height);
  let sum = 0;
  for (let i = 0; i < width * height; i++) {
    const v = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
    g[i] = v;
    sum += v;
  }
  let n = 0;
  let mean = 0;
  let m2 = 0;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const lap = g[i - 1] + g[i + 1] + g[i - width] + g[i + width] - 4 * g[i];
      n++;
      const d = lap - mean;
      mean += d / n;
      m2 += d * (lap - mean);
    }
  }
  return { brightness: sum / (width * height), sharpness: n > 1 ? m2 / (n - 1) : 0 };
}

/** Why a photo cannot be saved, or null. */
export function verdict(q: Quality): string | null {
  if (q.brightness < MIN_BRIGHTNESS) return "Too dark: turn the torch on or move to the light, then take it again.";
  if (q.sharpness < MIN_SHARPNESS) return "Blurred: hold the phone still (lean on something) and take it again.";
  return null;
}
