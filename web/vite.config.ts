import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const buildStamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
const DEFAULT_BACKEND_PORT = 8000;
const DEFAULT_FRONTEND_PORT = 5173;

function coercePort(value: string | number | undefined, fallback: number): number {
  const parsed = Number(String(value ?? "").trim());
  if (!isFinite(parsed) || parsed % 1 !== 0 || parsed <= 0 || parsed >= 65536) {
    return fallback;
  }
  return parsed;
}

function readWorkbenchPort(key: "backend_port" | "frontend_port", fallback: number): number {
  try {
    const configText = readFileSync(resolve(__dirname, "..", "config.toml"), "utf-8");
    let inWorkbenchBlock = false;
    for (const line of configText.split(/\r?\n/)) {
      const trimmed = line.trim();
      const section = trimmed.match(/^\[(.+)\]$/);
      if (section) {
        inWorkbenchBlock = section[1] === "workbench";
        continue;
      }
      if (!inWorkbenchBlock) {
        continue;
      }
      const value = trimmed.match(new RegExp(`^${key}\\s*=\\s*"?([^"\\r\\n#]+)"?`))?.[1];
      if (value !== undefined) {
        return coercePort(value, fallback);
      }
    }
    return fallback;
  } catch {
    return fallback;
  }
}

function firstEnvPort(names: string[]): string | undefined {
  for (const name of names) {
    const value = String(process.env[name] ?? "").trim();
    if (value) {
      return value;
    }
  }
  return undefined;
}

const backendPort = coercePort(
  firstEnvPort(["VIBELUTION_PORT", "AGENT_WORKBENCH_BACKEND_PORT"]),
  readWorkbenchPort("backend_port", DEFAULT_BACKEND_PORT),
);
const frontendPort = coercePort(
  firstEnvPort(["VIBELUTION_FRONTEND_PORT", "AGENT_WORKBENCH_FRONTEND_PORT"]),
  readWorkbenchPort("frontend_port", DEFAULT_FRONTEND_PORT),
);

export default defineConfig({
  define: {
    __VIBELUTION_BUILD_ID__: JSON.stringify(buildStamp),
  },
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: frontendPort,
    proxy: {
      "/api": `http://127.0.0.1:${backendPort}`,
    },
  },
});
