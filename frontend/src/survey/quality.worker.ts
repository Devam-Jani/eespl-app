// Runs the blur / brightness check off the main thread.
import { quality } from "./quality";

self.onmessage = (e: MessageEvent<{ data: Uint8ClampedArray; width: number; height: number }>) => {
  const { data, width, height } = e.data;
  self.postMessage(quality(data, width, height));
};
