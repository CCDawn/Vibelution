import { describe, expect, it, vi } from "vitest";
import { launcherAssistantPageNotices, type LauncherNoticeRead } from "./launcherAssistantPageNotices";

function read(label: string, failed = true): LauncherNoticeRead {
  return { label, failed, pending: false, error: new Error("ASSISTANT_REQUEST_TIMEOUT"), retry: vi.fn() };
}

describe("Launcher page-level notices", () => {
  it("groups failed reads and retries only those readers, never image or healthy sources", async () => {
    const reads = [read("会话刷新"), read("待授权查询"), read("任务状态", false)];
    const appearance = [read("头像")];
    const notices = launcherAssistantPageNotices({ lang: "zh", reads, appearance });
    expect(notices).toHaveLength(2);
    expect(notices[0].labels).toEqual(["会话刷新", "待授权查询"]);
    expect(notices[1].tone).toBe("info");
    await notices[0].actions?.[0].run();
    expect(reads[0].retry).toHaveBeenCalledOnce();
    expect(reads[1].retry).toHaveBeenCalledOnce();
    expect(reads[2].retry).not.toHaveBeenCalled();
    expect(appearance[0].retry).not.toHaveBeenCalled();
  });

  it("clears recovered sources, bounds diagnostics, and preserves the remaining category", () => {
    const source = { ...read("detail"), error: new Error("x".repeat(4_000)) };
    expect(launcherAssistantPageNotices({ lang: "en", reads: [source], appearance: [] })[0].details?.length).toBeLessThan(550);
    const notices = launcherAssistantPageNotices({ lang: "en", reads: [{ ...source, failed: false }], appearance: [read("avatar")] });
    expect(notices.map(notice => notice.kind)).toEqual(["appearance"]);
    expect(launcherAssistantPageNotices({ lang: "zh", reads: [], appearance: [] })).toEqual([]);
  });
});
