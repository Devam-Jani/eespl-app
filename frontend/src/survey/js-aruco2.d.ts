// js-aruco2 ships no types: the parts the measuring camera uses.
declare module "js-aruco2" {
  type Point = { x: number; y: number };
  export const AR: {
    Detector: new (config?: { dictionaryName?: string; maxHammingDistance?: number }) => {
      detect(image: { width: number; height: number; data: Uint8ClampedArray }): { id: number; corners: Point[]; hammingDistance: number }[];
    };
    Dictionary: new (name: string) => { codeList: string[]; nBits: number; tau: number };
  };
}
