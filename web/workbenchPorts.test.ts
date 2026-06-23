import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const originalBackendPort = process.env.VIBELUTION_PORT;
const originalFrontendPort = process.env.VIBELUTION_FRONTEND_PORT;
const originalAgentBackendPort = process.env.AGENT_WORKBENCH_BACKEND_PORT;
const originalAgentFrontendPort = process.env.AGENT_WORKBENCH_FRONTEND_PORT;
const originalConfigPath = process.env.VIBELUTION_CONFIG_PATH;
const originalConfigHome = process.env.VIBELUTION_CONFIG_HOME;
const originalUserProfile = process.env.USERPROFILE;
const originalHome = process.env.HOME;
const originalConfig = "[workbench]\nbackend_port = 8000\nfrontend_port = 5173\n";
let tempRoot = "";
let configPath = "";

function restoreEnv(name: string, value: string | undefined) {
  if (value === undefined) {
    delete process.env[name];
    return;
  }
  process.env[name] = value;
}

async function loadViteConfig() {
  vi.resetModules();
  return (await import("./vite.config.ts")).default;
}

beforeEach(() => {
  tempRoot = mkdtempSync(join(tmpdir(), "vibelution-vite-config-"));
  configPath = join(tempRoot, "config.toml");
  writeFileSync(configPath, originalConfig, "utf-8");
  process.env.VIBELUTION_CONFIG_PATH = configPath;
  delete process.env.VIBELUTION_CONFIG_HOME;
});

afterEach(() => {
  restoreEnv("VIBELUTION_PORT", originalBackendPort);
  restoreEnv("VIBELUTION_FRONTEND_PORT", originalFrontendPort);
  restoreEnv("AGENT_WORKBENCH_BACKEND_PORT", originalAgentBackendPort);
  restoreEnv("AGENT_WORKBENCH_FRONTEND_PORT", originalAgentFrontendPort);
  restoreEnv("VIBELUTION_CONFIG_PATH", originalConfigPath);
  restoreEnv("VIBELUTION_CONFIG_HOME", originalConfigHome);
  restoreEnv("USERPROFILE", originalUserProfile);
  restoreEnv("HOME", originalHome);
  if (tempRoot) {
    rmSync(tempRoot, { force: true, recursive: true });
    tempRoot = "";
    configPath = "";
  }
});

describe("vite workbench ports", () => {
  it("uses workbench config defaults for the dev server and api proxy", async () => {
    delete process.env.VIBELUTION_PORT;
    delete process.env.VIBELUTION_FRONTEND_PORT;

    const config = await loadViteConfig();

    expect(config.server?.host).toBe("127.0.0.1");
    expect(config.server?.port).toBe(5173);
    expect(config.server?.proxy?.["/api"]).toBe("http://127.0.0.1:8000");
  });

  it("uses saved non-default workbench ports without environment overrides", async () => {
    delete process.env.VIBELUTION_PORT;
    delete process.env.VIBELUTION_FRONTEND_PORT;
    writeFileSync(
      configPath,
      originalConfig.replace(
        /\[workbench\]\s*backend_port = \d+\s*frontend_port = \d+/,
        "[workbench]\nbackend_port = 9101\nfrontend_port = 6200",
      ),
      "utf-8",
    );

    const config = await loadViteConfig();

    expect(config.server?.port).toBe(6200);
    expect(config.server?.proxy?.["/api"]).toBe("http://127.0.0.1:9101");
  });

  it("keeps explicit environment ports as temporary overrides", async () => {
    process.env.VIBELUTION_PORT = "9101";
    process.env.VIBELUTION_FRONTEND_PORT = "6200";

    const config = await loadViteConfig();

    expect(config.server?.port).toBe(6200);
    expect(config.server?.proxy?.["/api"]).toBe("http://127.0.0.1:9101");
  });

  it("accepts agent workbench port aliases when explicit Vibelution ports are absent", async () => {
    delete process.env.VIBELUTION_PORT;
    delete process.env.VIBELUTION_FRONTEND_PORT;
    process.env.AGENT_WORKBENCH_BACKEND_PORT = "9101";
    process.env.AGENT_WORKBENCH_FRONTEND_PORT = "6200";

    const config = await loadViteConfig();

    expect(config.server?.port).toBe(6200);
    expect(config.server?.proxy?.["/api"]).toBe("http://127.0.0.1:9101");
  });

  it("falls back to built-in defaults instead of reading a project-root config", async () => {
    delete process.env.VIBELUTION_PORT;
    delete process.env.VIBELUTION_FRONTEND_PORT;
    delete process.env.VIBELUTION_CONFIG_PATH;
    delete process.env.VIBELUTION_CONFIG_HOME;
    process.env.USERPROFILE = tempRoot;
    process.env.HOME = tempRoot;

    const config = await loadViteConfig();

    expect(config.server?.port).toBe(5173);
    expect(config.server?.proxy?.["/api"]).toBe("http://127.0.0.1:8000");
  });

  it("keeps build warning noise delegated to the bundle budget guard", async () => {
    const config = await loadViteConfig();

    expect(config.build?.chunkSizeWarningLimit).toBe(760);
    expect("esbuild" in config).toBe(false);
  });
});
