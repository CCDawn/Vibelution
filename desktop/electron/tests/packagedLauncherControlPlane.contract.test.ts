import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { createDesktopLaunchProfile, serializeDesktopLaunchProfile } from "../src/launch/desktopLaunchProfileWriter.js";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));
const clientSourcePath = fileURLToPath(new URL("../src/process/launcherServiceClient.ts", import.meta.url));
const launcherApiSourcePath = fileURLToPath(new URL("../../../web/src/api/launcher.ts", import.meta.url));

describe("packaged Launcher control plane", () => {
  it("does not spawn or attach Python :8765 from Electron main", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("bootstrapMainOwnedLauncher(paths)");
    expect(source).toContain("resolve-workbench");
    expect(source).not.toContain("bootstrapPythonLauncherService(");
    expect(source).not.toContain("--attach-healthy-launcher");
    expect(source).not.toMatch(/127\.0\.0\.1:8765/);
  });

  it("keeps launcherServiceClient as leftover stop-only, never a :8765 bootstrap", () => {
    const source = readFileSync(clientSourcePath, "utf8");

    expect(source).toContain('"stop-launcher"');
    expect(source).toContain("windowsHide: true");
    expect(source).toContain("--use-state-owned-backend-pid");
    expect(source).not.toContain("bootstrapPythonLauncherService");
    expect(source).not.toContain('"bootstrap"');
    expect(source).not.toContain("--attach-healthy-launcher");
    expect(source).not.toMatch(/8765/);
  });

  it("writes launch profiles with operatorConfigPath only", () => {
    const serialized = serializeDesktopLaunchProfile(
      createDesktopLaunchProfile({
        workspaceRoot: "C:/repo",
        operatorConfigPath: "C:/operator/config.toml",
        pythonPath: "C:/Python/python.exe"
      })
    );
    const parsed = JSON.parse(serialized) as Record<string, unknown>;

    expect(Object.keys(parsed)).toEqual([
      "schemaVersion",
      "workspaceRoot",
      "operatorConfigPath",
      "pythonPath"
    ]);
    expect(parsed).not.toHaveProperty("configPath");
  });

  it("keeps the product launcher.ts transport on IPC, not :8765 fetch", () => {
    const source = readFileSync(launcherApiSourcePath, "utf8");

    expect(source).toContain("Launcher IPC bridge is not available.");
    expect(source).not.toMatch(/127\.0\.0\.1:8765/);
    expect(source).not.toContain("DEFAULT_LAUNCHER_CONTROL_PORT");
  });
});
