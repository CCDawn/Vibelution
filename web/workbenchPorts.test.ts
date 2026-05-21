import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

const originalBackendPort = process.env.VIBELUTION_PORT;
const originalFrontendPort = process.env.VIBELUTION_FRONTEND_PORT;
const originalAgentBackendPort = process.env.AGENT_WORKBENCH_BACKEND_PORT;
const originalAgentFrontendPort = process.env.AGENT_WORKBENCH_FRONTEND_PORT;
const configPath = resolve(__dirname, "..", "config.toml");
const originalConfig = readFileSync(configPath, "utf-8");

async function loadViteConfig() {
  vi.resetModules();
  return (await import("./vite.config.ts")).default;
}

afterEach(() => {
  process.env.VIBELUTION_PORT = originalBackendPort;
  process.env.VIBELUTION_FRONTEND_PORT = originalFrontendPort;
  process.env.AGENT_WORKBENCH_BACKEND_PORT = originalAgentBackendPort;
  process.env.AGENT_WORKBENCH_FRONTEND_PORT = originalAgentFrontendPort;
  writeFileSync(configPath, originalConfig, "utf-8");
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
});
