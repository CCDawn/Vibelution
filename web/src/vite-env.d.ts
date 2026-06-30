/// <reference types="vite/client" />

declare module "*.css";

declare module "*?raw" {
  const source: string;
  export default source;
}
