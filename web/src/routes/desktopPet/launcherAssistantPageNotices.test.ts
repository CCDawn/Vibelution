import { describe, expect, it, vi } from "vitest";
import { launcherAssistantPageNotices, launcherNoticeReadFailed, type LauncherNoticeRead } from "./launcherAssistantPageNotices";

function read(label: string, failed = true): LauncherNoticeRead {
  return { label, failed, pending: false, error: new Error("ASSISTANT_REQUEST_TIMEOUT"), retry: vi.fn() };
}

describe("Launcher page-level notices", () => {
  it("groups failed reads and retries only those readers, never image or healthy sources", async () => {
    const reads: LauncherNoticeRead[] = [
      { ...read("会话刷新"), feature: "conversation" },
      { ...read("待授权查询"), feature: "approvals" },
      { ...read("任务状态", false), feature: "tasks" },
      { ...read("另一处会话读取"), feature: "conversation" },
    ];
    const appearance = [read("头像")];
    const notices = launcherAssistantPageNotices({ lang: "zh", reads, appearance });
    expect(notices).toHaveLength(2);
    expect(notices[0].labels).toEqual(["会话刷新", "待授权查询", "另一处会话读取"]);
    expect(notices[0].features).toEqual(["conversation", "approvals"]);
    expect(notices[0].title).toBe("聊天没能刷新");
    expect(notices[0].description).toBe("稍后再试一次。");
    expect(notices[0].actions?.[0].label).toBe("再试一次");
    expect(notices[1].tone).toBe("info");
    await notices[0].actions?.[0].run();
    expect(reads[0].retry).toHaveBeenCalledOnce();
    expect(reads[1].retry).toHaveBeenCalledOnce();
    expect(reads[2].retry).not.toHaveBeenCalled();
    expect(reads[3].retry).toHaveBeenCalledOnce();
    expect(appearance[0].retry).not.toHaveBeenCalled();
  });

  it("keeps the initial failure visible while retrying, then clears it on recovery", () => {
    const initial = { isError: false, isPending: true, errorUpdatedAt: 0 };
    expect(launcherNoticeReadFailed(initial)).toBe(false);
    expect(launcherNoticeReadFailed({ ...initial, isPending: false, isError: true, errorUpdatedAt: 1 })).toBe(true);
    const failed = launcherNoticeReadFailed({ ...initial, errorUpdatedAt: 1 });
    const notices = launcherAssistantPageNotices({ lang: "en", reads: [{ ...read("Conversation"), failed, pending: true }], appearance: [] });
    expect(notices).toHaveLength(1);
    expect(notices[0].actions?.[0]).toMatchObject({ label: "Try again", pending: true });
    expect(launcherNoticeReadFailed({ ...initial, isPending: false, errorUpdatedAt: 1 })).toBe(false);
  });

  it("waits for every failed read even when one retry throws synchronously", async () => {
    let finish!: () => void;
    const remaining = new Promise<void>(resolve => { finish = resolve; });
    const reads = [
      { ...read("first"), retry: vi.fn(() => { throw new Error("ASSISTANT_REQUEST_TIMEOUT"); }) },
      { ...read("second"), retry: vi.fn(() => remaining) },
    ];
    const action = launcherAssistantPageNotices({ lang: "en", reads, appearance: [] })[0].actions![0];
    let settled = false;
    const retry = Promise.resolve(action.run()).then(() => { settled = true; });
    await Promise.resolve();
    await Promise.resolve();
    expect(reads[0].retry).toHaveBeenCalledOnce();
    expect(reads[1].retry).toHaveBeenCalledOnce();
    expect(settled).toBe(false);
    finish();
    await retry;
    expect(settled).toBe(true);
  });

  it.each([
    "ASSISTANT_REQUEST_TIMEOUT",
    new Error("ASSISTANT_REQUEST_TIMEOUT"),
    "Error invoking remote method 'launcherAssistant:invoke': Error: ASSISTANT_REQUEST_TIMEOUT",
    new Error("Error invoking remote method 'launcherAssistant:invoke': ASSISTANT_REQUEST_TIMEOUT"),
    new Error('Error invoking remote method "launcherAssistant:invoke": Error: ASSISTANT_REQUEST_TIMEOUT'),
    "Error invoking remote method launcher-assistant: ASSISTANT_REQUEST_TIMEOUT",
    new Error("Error invoking remote method assistant:invoke: Error: ASSISTANT_REQUEST_TIMEOUT"),
  ])("shows the assistant error code without an IPC wrapper: %s", error => {
    const notices = launcherAssistantPageNotices({ lang: "en", reads: [{ ...read("detail"), error }], appearance: [] });
    expect(notices[0].details).toBe("detail: ASSISTANT_REQUEST_TIMEOUT");
  });

  it("keeps different read errors separate without inferring a shared cause", () => {
    const notices = launcherAssistantPageNotices({ lang: "en", reads: [
      { ...read("detail"), error: new Error("ASSISTANT_REQUEST_TIMEOUT") },
      { ...read("approvals"), error: "ASSISTANT_RESPONSE_INVALID" },
    ], appearance: [] });
    expect(notices[0].details).toBe("detail: ASSISTANT_REQUEST_TIMEOUT\napprovals: ASSISTANT_RESPONSE_INVALID");
    expect(notices[0].description).toBe("Try again in a moment.");
  });

  it.each([
    "'launcherAssistant:invoke'", '"launcherAssistant:invoke"', "launcher-assistant", "assistant:invoke",
  ].flatMap(method => ["", "Error: "].map(prefix => ({ method, prefix }))))(
    "removes the $method IPC wrapper with '$prefix' and preserves the error body",
    ({ method, prefix }) => {
      const error = new Error(`Error invoking remote method ${method}: ${prefix}detail: response unavailable`);
      const notices = launcherAssistantPageNotices({ lang: "en", reads: [{ ...read("detail"), error }], appearance: [] });
      expect(notices[0].details).toBe("detail: detail: response unavailable");
    },
  );

  it("removes the IPC wrapper and bounds an unknown error", () => {
    const error = new Error(`Error invoking remote method 'launcherAssistant:invoke': Error: ${"x".repeat(4_000)}`);
    const notices = launcherAssistantPageNotices({ lang: "en", reads: [{ ...read("detail"), error }], appearance: [] });
    expect(notices[0].details).toBe(`detail: ${"x".repeat(500)}`);
  });

  it("clears recovered sources, bounds diagnostics, and preserves the remaining category", () => {
    const source = { ...read("detail"), error: new Error("x".repeat(4_000)) };
    expect(launcherAssistantPageNotices({ lang: "en", reads: [source], appearance: [] })[0].details?.length).toBeLessThan(550);
    const notices = launcherAssistantPageNotices({ lang: "en", reads: [{ ...source, failed: false }], appearance: [read("avatar")] });
    expect(notices.map(notice => notice.kind)).toEqual(["appearance"]);
    expect(launcherAssistantPageNotices({ lang: "zh", reads: [], appearance: [] })).toEqual([]);
  });
});
