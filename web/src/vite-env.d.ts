/// <reference types="vite/client" />

declare module "*.module.css" {
  const classes: Record<string, string>;
  export default classes;
}

declare module "*.css";

declare module "*?raw" {
  const source: string;
  export default source;
}
