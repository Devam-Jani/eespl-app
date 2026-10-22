// Vite: a "?url" import is the asset's URL (the web-ifc WebAssembly for the BIM view).
declare module "*?url" {
  const url: string;
  export default url;
}
