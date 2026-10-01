import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  UPDATE_BANNER_DISMISSED_STORAGE_KEY,
  isUpdateBannerVerdict,
  readStoredUpdateBannerDismissedHead,
  shouldShowUpdateBanner,
  storeUpdateBannerDismissedHead,
  updateBannerCopy,
  updateBannerHeadToken,
  updateBannerRestartReloadsDocument,
} from "./updateBanner";

describe("updateBanner verdict gate", () => {
  it("prompts for every verdict where the backend runs stale code", () => {
    expect(isUpdateBannerVerdict("backend_behind")).toBe(true);
    expect(isUpdateBannerVerdict("backend_and_frontend_behind")).toBe(true);
  });

  it("does not prompt for current, frontend-only, or unknown verdicts", () => {
    expect(isUpdateBannerVerdict("current")).toBe(false);
    expect(isUpdateBannerVerdict("frontend_behind")).toBe(false);
    expect(isUpdateBannerVerdict("unknown")).toBe(false);
    expect(isUpdateBannerVerdict(undefined)).toBe(false);
    expect(isUpdateBannerVerdict(null)).toBe(false);
  });
});

describe("shouldShowUpdateBanner", () => {
  it("shows when the backend is behind and no dismissal matches the disk HEAD", () => {
    expect(shouldShowUpdateBanner({
      verdict: "backend_behind",
      diskHead: "e91a851dfabc",
      dismissedHead: "",
    })).toBe(true);
    expect(shouldShowUpdateBanner({
      verdict: "backend_and_frontend_behind",
      diskHead: "e91a851dfabc",
      dismissedHead: "0d6622f79old",
    })).toBe(true);
  });

  it("stays hidden for current verdicts, missing HEAD, and a matching dismissal", () => {
    expect(shouldShowUpdateBanner({
      verdict: "current",
      diskHead: "e91a851dfabc",
      dismissedHead: "",
    })).toBe(false);
    expect(shouldShowUpdateBanner({
      verdict: "backend_behind",
      diskHead: "",
      dismissedHead: "",
    })).toBe(false);
    expect(shouldShowUpdateBanner({
      verdict: "backend_behind",
      diskHead: undefined,
      dismissedHead: "",
    })).toBe(false);
    // Dismissed for THIS commit: no repeat, ...
    expect(shouldShowUpdateBanner({
      verdict: "backend_behind",
      diskHead: "e91a851dfabc",
      dismissedHead: "e91a851dfabc",
    })).toBe(false);
    // ... but a NEW commit re-prompts.
    expect(shouldShowUpdateBanner({
      verdict: "backend_behind",
      diskHead: "newcommit999",
      dismissedHead: "e91a851dfabc",
    })).toBe(true);
  });
});

describe("updateBannerCopy", () => {
  it("bilingual title carries the restart-to-apply message", () => {
    expect(updateBannerCopy("zh", "e91a851dfabc", false).title).toBe("代码已更新，重启后生效");
    expect(updateBannerCopy("en", "e91a851dfabc", false).title).toBe("Code updated — restart to apply");
  });

  it("detail names the moved-ahead main with a short commit token", () => {
    expect(updateBannerCopy("zh", "e91a851dfabc", false).detail).toBe("main 已前进到 @e91a851。");
    expect(updateBannerCopy("en", "e91a851dfabc", false).detail).toBe("main has moved ahead to @e91a851.");
  });

  it("mentions the frontend build only when it is also behind", () => {
    expect(updateBannerCopy("zh", "e91a851dfabc", true).detail)
      .toBe("main 已前进到 @e91a851。 重启会同时加载新的前端构建。");
    expect(updateBannerCopy("en", "e91a851dfabc", true).detail)
      .toBe("main has moved ahead to @e91a851. The restart also loads the new frontend build.");
  });

  it("degrades gracefully without a HEAD", () => {
    expect(updateBannerHeadToken("")).toBe("");
    expect(updateBannerCopy("zh", "", false).detail).toBe("main 已前进。");
  });

  it("speaks about uncommitted workspace changes when only the dirty digest differs", () => {
    // behindCount null/0 with a behind verdict = no new commits on main; the
    // copy must not claim that main moved ahead.
    for (const commitsBehind of [null, 0]) {
      const zh = updateBannerCopy("zh", "e91a851dfabc", false, commitsBehind);
      expect(zh.title).toBe("工作区有未提交变化，重启后生效");
      expect(zh.detail).toContain("工作区");
      expect(zh.detail).not.toContain("main 已前进");

      const en = updateBannerCopy("en", "e91a851dfabc", false, commitsBehind);
      expect(en.title).toBe("Working tree changed — restart to apply");
      expect(en.detail).toContain("working-tree state");
      expect(en.detail).not.toContain("main has moved ahead");
    }
  });

  it("keeps the moved-ahead copy for real commit divergence and unknown counts", () => {
    expect(updateBannerCopy("zh", "e91a851dfabc", false, 3).detail).toBe("main 已前进到 @e91a851。");
    // A caller that cannot tell keeps the previous framing.
    expect(updateBannerCopy("zh", "e91a851dfabc", false, undefined).detail).toBe("main 已前进到 @e91a851。");
  });

  it("still mentions the frontend build in the dirty-workspace variant when it is also behind", () => {
    expect(updateBannerCopy("zh", "e91a851dfabc", true, null).detail)
      .toBe("运行中的代码基于较早的工作区状态，重启后会按当前代码运行。 重启会同时加载新的前端构建。");
    expect(updateBannerCopy("en", "e91a851dfabc", true, null).detail)
      .toBe("The running code was loaded from an earlier working-tree state; restart to serve the current changes. The restart also loads the new frontend build.");
  });
});

describe("updateBannerRestartReloadsDocument", () => {
  it("reloads the open document after an accepted restart so the new frontend build loads", () => {
    expect(updateBannerRestartReloadsDocument(undefined)).toBe(true);
    expect(updateBannerRestartReloadsDocument("")).toBe(true);
    expect(updateBannerRestartReloadsDocument("restart_accepted", true)).toBe(true);
  });

  it("leaves the current document in place when the restart was only queued", () => {
    expect(updateBannerRestartReloadsDocument("restart_queued")).toBe(false);
    expect(updateBannerRestartReloadsDocument(" restart_queued ")).toBe(false);
    expect(updateBannerRestartReloadsDocument("restart_queued", true)).toBe(false);
  });

  it("leaves the current document in place when the Launcher rejects the restart", () => {
    expect(updateBannerRestartReloadsDocument("user_restart_pause_failed", false)).toBe(false);
    expect(updateBannerRestartReloadsDocument("unexpected_rejection", false)).toBe(false);
  });
});

describe("updateBanner dismissed-head storage", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
    });
    vi.stubGlobal("window", { localStorage: globalThis.localStorage });
  });

  it("persists the dismissed commit under the dedicated key", () => {
    expect(readStoredUpdateBannerDismissedHead()).toBe("");
    storeUpdateBannerDismissedHead("e91a851dfabc");
    expect(readStoredUpdateBannerDismissedHead()).toBe("e91a851dfabc");
    expect(localStorage.getItem(UPDATE_BANNER_DISMISSED_STORAGE_KEY)).toBe("e91a851dfabc");
  });

  it("falls back to the in-memory dismissal when storage throws", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("storage blocked");
      },
      setItem: () => {
        throw new Error("storage blocked");
      },
    });
    vi.stubGlobal("window", { localStorage: globalThis.localStorage });
    expect(readStoredUpdateBannerDismissedHead()).toBe("");
    expect(() => storeUpdateBannerDismissedHead("e91a851dfabc")).not.toThrow();
  });

  it("reads nothing when window is unavailable", () => {
    vi.stubGlobal("window", undefined);
    expect(readStoredUpdateBannerDismissedHead()).toBe("");
    expect(() => storeUpdateBannerDismissedHead("e91a851dfabc")).not.toThrow();
  });
});
