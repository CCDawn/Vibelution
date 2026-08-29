import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  createSingleInstanceEnvelope,
  pinSharedDesktopShellUserData,
  resolveDesktopShellUserDataRoot,
  resolveSingleInstanceProvenance,
  resolveSecondInstanceIntent,
  shouldPinSharedDesktopShellUserData,
  shouldRunDesktopWhenReadyHandlers,
  singleInstanceDecision
} from "../src/appLock.js";
import { createDesktopPaths, resolveWorkspaceRuntimeDir } from "../src/paths.js";

describe("Electron desktop paths", () => {
  it("keeps launcher runtime state under the external workspace", () => {
    const paths = createDesktopPaths({
      importMetaUrl: "file:///C:/Program%20Files/Vibelution/resources/app.asar/dist/main.js",
      resourcesRoot: "C:/Program Files/Vibelution/resources",
      userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution",
      workspaceRoot: "C:/repo"
    });
    expect(resolveWorkspaceRuntimeDir(paths).replace(/\\/g, "/")).toBe("C:/repo/.runtime/launcher");
  });
});

describe("singleInstanceDecision", () => {
  it("continues as primary when the app owns the lock", () => {
    expect(singleInstanceDecision(true)).toEqual({ action: "continue_as_primary" });
  });

  it("focuses the existing launcher for secondary launches", () => {
    expect(singleInstanceDecision(false)).toEqual({ action: "focus_existing", reason: "secondary_launch" });
  });
});

describe("single-instance lifecycle envelope", () => {
  it("defaults legacy or malformed second-instance metadata to operator", () => {
    expect(resolveSingleInstanceProvenance(undefined)).toBe("operator");
    expect(resolveSingleInstanceProvenance({})).toBe("operator");
    expect(
      resolveSingleInstanceProvenance({
        schemaVersion: 1,
        kind: "not-vibelution",
        lifecycle: { provenance: "forwarded" }
      })
    ).toBe("operator");
  });

  it("round-trips explicit Runtime Manager forwarding provenance", () => {
    const envelope = createSingleInstanceEnvelope({
      lifecycleCommand: "stop",
      lifecycleSource: "web_ui",
      lifecycleReason: "web_close_button",
      lifecycleStopManager: false,
      explicitlyForwarded: true
    });
    expect(envelope).toEqual({
      schemaVersion: 1,
      kind: "vibelution-single-instance",
      lifecycle: {
        command: "stop",
        provenance: "forwarded",
        source: "web_ui",
        reason: "web_close_button",
        stopManager: false
      }
    });
    expect(resolveSingleInstanceProvenance(envelope)).toBe("forwarded");
  });

  it("encodes a plain CLI lifecycle launch as operator provenance", () => {
    const envelope = createSingleInstanceEnvelope({ lifecycleCommand: "stop" });
    expect(envelope).toEqual({
      schemaVersion: 1,
      kind: "vibelution-single-instance",
      lifecycle: {
        command: "stop",
        provenance: "operator"
      }
    });
    expect(resolveSingleInstanceProvenance(envelope)).toBe("operator");
  });
});

describe("shouldRunDesktopWhenReadyHandlers", () => {
  it("keeps smoke and close-canary instances on the whenReady path", () => {
    expect(
      shouldRunDesktopWhenReadyHandlers({
        lockAction: "focus_existing",
        smoke: true
      })
    ).toBe(true);
    expect(
      shouldRunDesktopWhenReadyHandlers({
        lockAction: "focus_existing",
        smoke: false,
        workbenchCloseCanary: true
      })
    ).toBe(true);
  });

  it("skips product whenReady on a secondary instance so reap cannot race start", () => {
    expect(
      shouldRunDesktopWhenReadyHandlers({
        lockAction: "focus_existing",
        smoke: false
      })
    ).toBe(false);
    expect(
      shouldRunDesktopWhenReadyHandlers({
        lockAction: "continue_as_primary",
        smoke: false
      })
    ).toBe(true);
  });
});

describe("shared desktop-shell userData lock", () => {
  it("pins packaged and unpackaged shells to the same LocalAppData directory", () => {
    expect(
      resolveDesktopShellUserDataRoot({
        LOCALAPPDATA: "C:/Users/17533/AppData/Local"
      }).replace(/\\/g, "/")
    ).toBe("C:/Users/17533/AppData/Local/Vibelution/DesktopShell");
    expect(shouldPinSharedDesktopShellUserData({ smoke: false })).toBe(true);
    expect(shouldPinSharedDesktopShellUserData({ smoke: true })).toBe(false);
    expect(shouldPinSharedDesktopShellUserData({ smoke: false, workbenchCloseCanary: true })).toBe(false);
  });

  it("falls back to USERPROFILE when LOCALAPPDATA is missing", () => {
    expect(
      resolveDesktopShellUserDataRoot({
        USERPROFILE: "C:/Users/17533"
      }).replace(/\\/g, "/")
    ).toBe("C:/Users/17533/AppData/Local/Vibelution/DesktopShell");
  });

  it("sets userData before the Electron lock for product launches and skips smoke isolation", () => {
    const paths: Array<{ name: string; path: string }> = [];
    const product = pinSharedDesktopShellUserData(
      {
        setPath(name, path) {
          paths.push({ name, path });
        }
      },
      { smoke: false, env: { LOCALAPPDATA: "D:/Local" } }
    );
    const smoke = pinSharedDesktopShellUserData(
      {
        setPath() {
          throw new Error("smoke must not pin shared userData");
        }
      },
      { smoke: true, env: { LOCALAPPDATA: "D:/Local" } }
    );

    expect(product).toEqual({
      pinned: true,
      userDataRoot: join("D:/Local", "Vibelution", "DesktopShell")
    });
    expect(paths).toEqual([{ name: "userData", path: product.userDataRoot }]);
    expect(smoke).toEqual({ pinned: false, userDataRoot: "" });
  });
});

describe("resolveSecondInstanceIntent", () => {
  it("keeps explicit deep-link, project, and workbench intents", () => {
    expect(resolveSecondInstanceIntent({ deepLinkUrl: "vibelution://focus" })).toEqual({
      action: "handle_deep_link",
      rawUrl: "vibelution://focus"
    });
    expect(resolveSecondInstanceIntent({ projectRoot: "C:/repo" })).toEqual({
      action: "apply_project",
      projectRoot: "C:/repo",
      lifecycleCommand: ""
    });
    expect(resolveSecondInstanceIntent({ openWorkbench: true })).toEqual({ action: "open_workbench" });
  });

  it("focuses the existing desktop shell for a bare shortcut re-click", () => {
    expect(resolveSecondInstanceIntent({})).toEqual({ action: "focus_existing_shell" });
    expect(resolveSecondInstanceIntent({ deepLinkUrl: "   ", projectRoot: "", openWorkbench: false })).toEqual({
      action: "focus_existing_shell"
    });
  });

  it("applies --project before start instead of forwarding start to main", () => {
    expect(
      resolveSecondInstanceIntent({
        projectRoot: "C:/repo/.worktrees/task",
        lifecycleCommand: "start"
      })
    ).toEqual({
      action: "apply_project",
      projectRoot: "C:/repo/.worktrees/task",
      lifecycleCommand: "start"
    });
    expect(resolveSecondInstanceIntent({ lifecycleCommand: "start" })).toEqual({
      action: "lifecycle",
      command: "start"
    });
  });
});
