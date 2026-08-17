import { describe, expect, it } from "vitest";

import { overlayLauncherWindowTruth } from "../src/windows/launcherWindowTruthOverlay.js";
import { createLocalLauncherStatusSnapshot } from "../src/protocol/launcherStatusSnapshot.js";

describe("createLocalLauncherStatusSnapshot", () => {
  it("stays partial when Electron has a window but the local snapshot has no ready backend", () => {
    const snapshot = createLocalLauncherStatusSnapshot();
    expect(snapshot.launcher).toMatchObject({
      mode: "standalone_control_plane",
      controlPlane: { adapter: "electron_main", port: 0 }
    });
    const overlaid = overlayLauncherWindowTruth(
      "status",
      snapshot,
      { workbench: { open: true, rendererProcessId: 4242 }, instances: [] }
    ) as Record<string, unknown>;
    const bundle = overlaid.projectBundle as Record<string, unknown>;
    expect(bundle.observedState).toBe("partial");
    expect(bundle.lifecycleConsistency).toBe("backend_missing");
    expect(bundle.browser).toMatchObject({ alive: true, windowPid: 4242 });
  });
});
