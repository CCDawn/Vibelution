import tailwindcss from "@tailwindcss/vite";
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

function configPathCandidates(): string[] {
  const explicitPath = String(process.env.VIBELUTION_CONFIG_PATH ?? "").trim();
  if (explicitPath) {
    return [resolve(explicitPath)];
  }

  const explicitHome = String(process.env.VIBELUTION_CONFIG_HOME ?? "").trim();
  if (explicitHome) {
    return [resolve(explicitHome, "config.toml")];
  }

  const userRoot = String(process.env.USERPROFILE ?? process.env.HOME ?? "").trim();
  const candidates: string[] = [];
  if (userRoot) {
    candidates.push(resolve(userRoot, "Documents", "Vibelution", "config", "config.toml"));
  }
  return candidates;
}

function readWorkbenchPort(key: "backend_port" | "frontend_port", fallback: number): number {
  for (const configPath of configPathCandidates()) {
    let configText = "";
    try {
      configText = readFileSync(configPath, "utf-8");
    } catch {
      continue;
    }
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
  }
  return fallback;
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
  plugins: [tailwindcss(), react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "*.test.ts"],
  },
  build: {
    chunkSizeWarningLimit: 760,
  },
  server: {
    host: "127.0.0.1",
    port: frontendPort,
    proxy: {
      "/api": `http://127.0.0.1:${backendPort}`,
    },
  },
} as Parameters<typeof defineConfig>[0]);
