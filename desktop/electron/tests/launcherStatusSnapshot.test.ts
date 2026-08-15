import { describe, expect, it } from "vitest";

import { overlayLauncherWindowTruth } from "../src/windows/launcherWindowTruthOverlay.js";
import { createLocalLauncherStatusSnapshot } from "../src/protocol/launcherStatusSnapshot.js";

describe("createLocalLauncherStatusSnapshot", () => {
  it("is a closed workbench snapshot that overlay can mark open from Electron window truth", () => {
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
    expect(bundle.observedState).toBe("open");
    expect(bundle.browser).toMatchObject({ alive: true, windowPid: 4242 });
  });
});
