import { describe, expect, it } from "vitest";
import { createLauncherEnvironmentSummary, redactEnvironmentSummary } from "../src/protocol/environmentSummary.js";

describe("Launcher environment summary", () => {
  it("keeps external operator config explicit", () => {
    const summary = createLauncherEnvironmentSummary({
      schemaVersion: 1,
      paths: {
        desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
        resourcesRoot: "C:/Program Files/Vibelution/resources",
        workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
        userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution"
      },
      pythonSource: "launcher_resolver",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      launcherUrl: "http://127.0.0.1:8765/launcher",
      workbenchUrl: "http://127.0.0.1:8765/",
      controlTokenPresent: true,
      workspaceId: "workspace-vibelution",
      launcherInstanceId: "launcher-1",
      protocolVersion: 1,
      minDesktopProtocolVersion: 1,
      maxDesktopProtocolVersion: 1,
      capabilities: ["desktop_actions_v1", "window_state_lease_v1"],
      nodeEnv: "test"
    });

    expect(summary.operatorConfigPath.replace(/\\/g, "/")).toBe(
      "C:/Users/17533/Documents/Vibelution/config/config.toml"
    );
    expect(summary).not.toHaveProperty("controlToken");
  });

  it("redacts by reporting token presence only", () => {
    const summary = createLauncherEnvironmentSummary({
      schemaVersion: 1,
      paths: {
        desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
        resourcesRoot: "C:/Program Files/Vibelution/resources",
        workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
        userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution"
      },
      pythonSource: "env_override",
      pythonPath: "C:/Python/python.exe",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      launcherUrl: "http://127.0.0.1:8765/launcher",
      workbenchUrl: "http://127.0.0.1:8765/",
      controlTokenPresent: true,
      workspaceId: "workspace-vibelution",
      launcherInstanceId: "launcher-1",
      protocolVersion: 1,
      minDesktopProtocolVersion: 1,
      maxDesktopProtocolVersion: 1,
      capabilities: ["desktop_actions_v1", "window_state_lease_v1"],
      nodeEnv: "test"
    });

    expect(redactEnvironmentSummary(summary)).toEqual(summary);
  });
});
