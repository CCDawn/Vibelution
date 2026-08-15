import { describe, expect, it } from "vitest";

import {
  appendComposerQueueItem,
  appendImmediateSteerTurns,
  moveComposerQueueItem,
  removeComposerQueueItem,
  resolveComposerQueueEnter,
  resolveComposerQueuePrimaryKind,
  updateComposerQueueItem,
} from "./composerFollowupQueueModel";

const queued = [{ id: "q1", text: "先不要改测试" }];

describe("composerFollowupQueueModel", () => {
  it("queues text while the turn is running", () => {
    expect(resolveComposerQueueEnter({
      sessionBusy: true,
      draft: "先不要改测试",
      queue: [],
    })).toEqual({ type: "enqueue", text: "先不要改测试" });
    expect(resolveComposerQueuePrimaryKind({
      sessionBusy: true,
      draft: "先不要改测试",
      queueCount: 0,
    })).toBe("queue");
  });

  it("treats a second empty Enter as immediate steer", () => {
    expect(resolveComposerQueueEnter({
      sessionBusy: true,
      draft: "   ",
      queue: queued,
    })).toEqual({ type: "immediate", items: queued });
    expect(resolveComposerQueuePrimaryKind({
      sessionBusy: true,
      draft: "",
      queueCount: 1,
    })).toBe("immediate");
  });

  it("appends more text instead of flushing immediately", () => {
    expect(resolveComposerQueueEnter({
      sessionBusy: true,
      draft: "并且补一条日志",
      queue: queued,
    })).toEqual({ type: "enqueue", text: "并且补一条日志" });
  });

  it("sends normally when the session is idle", () => {
    expect(resolveComposerQueueEnter({
      sessionBusy: false,
      draft: "下一句",
      queue: [],
    })).toEqual({ type: "send", text: "下一句" });
  });

  it("appends immediate steer as its own user-side turn", () => {
    const original = { kind: "user", text: "把登录页改成暗色" };
    const assistant = { kind: "assistant", text: "正在改 LoginPage…" };
    const next = appendImmediateSteerTurns(
      [original, assistant],
      ["先不要改测试，只汇报改了哪些文件。"],
      (text) => ({ kind: "steer", text }),
    );
    expect(next).toHaveLength(3);
    expect(next[0]).toEqual(original);
    expect(next[1]).toEqual(assistant);
    expect(next[2]).toEqual({ kind: "steer", text: "先不要改测试，只汇报改了哪些文件。" });
  });

  it("supports withdraw, edit, append, and reorder", () => {
    const withSecond = appendComposerQueueItem(queued, "再检查权限");
    expect(withSecond).toHaveLength(2);
    expect(updateComposerQueueItem(withSecond, "q1", "先不要改测试，只汇报")[0]?.text).toBe("先不要改测试，只汇报");
    expect(removeComposerQueueItem(withSecond, "q1")).toEqual([withSecond[1]]);
    expect(moveComposerQueueItem(withSecond, 1, 0).map((item) => item.text)).toEqual([
      "再检查权限",
      "先不要改测试",
    ]);
  });
});
