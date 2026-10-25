import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  createSingleInstanceEnvelope,
  pinSharedDesktopShellUserData,
  resolveDesktopShellUserDataRoot,
  resolveSingleInstanceCliIntent,
  resolveSingleInstanceProvenance,
  resolveSecondInstanceIntent,
  shouldPinSharedDesktopShellUserData,
  shouldRunDesktopWhenReadyHandlers,
  singleInstanceDecision
} from "../src/appLock.js";
import { createDesktopPaths, resolveWorkspaceRuntimeDir } from "../src/paths.js";

describe("Electron desktop paths", () => {
  it.skipIf(process.platform !== "win32")("keeps launcher runtime state under the external workspace", () => {
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
  it.each(["C:/integration", "C:\\integration", "/integration", "\\\\server\\share\\integration"])(
    "preserves the explicit integration workspace independently of the worktree project: %s",
    (workspaceRoot) => {
      const envelope = createSingleInstanceEnvelope({
        workspaceRoot,
        projectRoot: "C:/integration/.worktrees/task",
        lifecycleCommand: "start"
      });
      expect(envelope.workspaceRoot).toBe(workspaceRoot);
      expect(resolveSingleInstanceCliIntent(envelope)).toEqual({
        workspaceRoot,
        projectRoot: "C:/integration/.worktrees/task",
        openWorkbench: false,
        hiddenPresentation: false,
        lifecycleCommand: "start"
      });
    }
  );

  it("omits an unspecified or empty workspace and does not infer one from a project or slot", () => {
    for (const input of [{}, { workspaceRoot: "" }]) {
      const envelope = createSingleInstanceEnvelope({ ...input, projectRoot: "C:/worktree" });
      expect(envelope).not.toHaveProperty("workspaceRoot");
      expect(resolveSingleInstanceCliIntent({ ...envelope, slotRoot: "C:/slot" })).toEqual({
        projectRoot: "C:/worktree", openWorkbench: false, hiddenPresentation: false, lifecycleCommand: ""
      });
      expect(resolveSingleInstanceCliIntent({ ...envelope, workspaceRoot: "" })).toHaveProperty("workspaceRoot", "");
    }
  });

  it.each(["C:/integration", "/integration"])("rejects assistant workspace conflicts: %s", (workspaceRoot) => {
    expect(() => createSingleInstanceEnvelope({ assistant: true, workspaceRoot })).toThrow("ASSISTANT_MODE_CONFLICT");
    expect(() => resolveSingleInstanceCliIntent({ ...createSingleInstanceEnvelope({ assistant: true }), workspaceRoot }))
      .toThrow("ASSISTANT_MODE_CONFLICT");
  });

  it.each([null, false, 42, {}, [], " C:/root", "C:/root ", "C:/root\u0000suffix", "relative/root", "C:foo", "\\relative", "https://example.com/root", "file:///C:/root"].map((value) => [value]))(
    "rejects malformed explicit workspace roots on both envelope boundaries: %j",
    (workspaceRoot) => {
      expect(() => createSingleInstanceEnvelope({ workspaceRoot } as unknown as Parameters<typeof createSingleInstanceEnvelope>[0]))
        .toThrow("INVALID_WORKSPACE_ROOT");
      expect(() => resolveSingleInstanceCliIntent({ ...createSingleInstanceEnvelope(), workspaceRoot }))
        .toThrow("INVALID_WORKSPACE_ROOT");
    }
  );

  it("rejects an explicitly undefined workspace in received metadata", () => {
    expect(() => resolveSingleInstanceCliIntent({ ...createSingleInstanceEnvelope(), workspaceRoot: undefined }))
      .toThrow("INVALID_WORKSPACE_ROOT");
  });

  it("forwards an assistant-only open to the same primary without project intent", () => {
    const envelope = createSingleInstanceEnvelope({ assistant: true, hiddenPresentation: true });
    expect(envelope).toMatchObject({ assistant: true, projectRoot: "", openWorkbench: false });
    const intent = resolveSingleInstanceCliIntent(envelope);
    expect(intent).toMatchObject({ assistant: true, hiddenPresentation: true });
    expect(resolveSecondInstanceIntent(intent)).toEqual({ action: "open_assistant", hiddenPresentation: true });
  });

  it("rejects conflicting assistant fields even in structured second-instance metadata", () => {
    expect(() => createSingleInstanceEnvelope({ assistant: true, projectRoot: "C:/project" })).toThrow("ASSISTANT_MODE_CONFLICT");
    expect(() => resolveSingleInstanceCliIntent({ ...createSingleInstanceEnvelope(), assistant: true, openWorkbench: true }))
      .toThrow("ASSISTANT_MODE_CONFLICT");
    expect(() => resolveSecondInstanceIntent({ assistant: true, lifecycleCommand: "start" })).toThrow("ASSISTANT_MODE_CONFLICT");
  });

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
      projectRoot: "",
      openWorkbench: false,
      hiddenPresentation: false,
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
      projectRoot: "",
      openWorkbench: false,
      hiddenPresentation: false,
      lifecycle: {
        command: "stop",
        provenance: "operator"
      }
    });
    expect(resolveSingleInstanceProvenance(envelope)).toBe("operator");
  });

  it("round-trips project lifecycle intent without relying on second-instance argv order", () => {
    const envelope = createSingleInstanceEnvelope({
      projectRoot: " C:/repo/.worktrees/task ",
      openWorkbench: true,
      lifecycleCommand: "START"
    });

    expect(resolveSingleInstanceCliIntent(envelope)).toEqual({
      projectRoot: "C:/repo/.worktrees/task",
      openWorkbench: true,
      hiddenPresentation: false,
      lifecycleCommand: "start"
    });
    expect(resolveSingleInstanceCliIntent({ schemaVersion: 1, kind: "other" })).toEqual({
      projectRoot: "",
      openWorkbench: false,
      hiddenPresentation: false,
      lifecycleCommand: ""
    });
  });

  it("round-trips hidden presentation through the envelope without defaulting it on", () => {
    const envelope = createSingleInstanceEnvelope({
      projectRoot: "C:/repo/.worktrees/task",
      lifecycleCommand: "start"
    });
    expect(envelope.hiddenPresentation).toBe(false);
    expect(resolveSingleInstanceCliIntent(envelope).hiddenPresentation).toBe(false);

    const hiddenEnvelope = createSingleInstanceEnvelope({
      projectRoot: "C:/repo/.worktrees/task",
      lifecycleCommand: "start",
      hiddenPresentation: true
    });
    expect(hiddenEnvelope.hiddenPresentation).toBe(true);
    expect(resolveSingleInstanceCliIntent(hiddenEnvelope)).toMatchObject({
      projectRoot: "C:/repo/.worktrees/task",
      openWorkbench: false,
      hiddenPresentation: true
    });
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
      lifecycleCommand: "",
      hiddenPresentation: false
    });
    expect(
      resolveSecondInstanceIntent({ projectRoot: "C:/repo", hiddenPresentation: true })
    ).toEqual({
      action: "apply_project",
      projectRoot: "C:/repo",
      lifecycleCommand: "",
      hiddenPresentation: true
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
      lifecycleCommand: "start",
      hiddenPresentation: false
    });
    expect(resolveSecondInstanceIntent({ lifecycleCommand: "start" })).toEqual({
      action: "lifecycle",
      command: "start"
    });
  });

  it("keeps an explicit lifecycle command when the launcher also requests a Workbench window", () => {
    expect(
      resolveSecondInstanceIntent({
        lifecycleCommand: "restart",
        openWorkbench: true
      })
    ).toEqual({
      action: "lifecycle",
      command: "restart"
    });
  });
});
