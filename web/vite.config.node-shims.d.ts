declare const __dirname: string;

declare var process: {
  env: Record<string, string | undefined>;
};

declare module "node:fs" {
  export function readFileSync(path: string, encoding: string): string;
}

declare module "node:path" {
  export function resolve(...paths: string[]): string;
}
