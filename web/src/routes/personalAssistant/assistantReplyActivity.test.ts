// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import type { SessionDetail } from "../../api/types";
import { assistantReplyIds, assistantReplyStore, EMPTY_REPLY_ACTIVITY, observeAssistantReplies } from "./assistantReplyActivity";

describe("assistant native reply activity", () => {
  it("adopts history, ignores clock-only refreshes and deduplicates replies", () => {
    const baseline = observeAssistantReplies(EMPTY_REPLY_ACTIVITY, ["t1:reply"], false, 100);
    expect(baseline.unread).toEqual([]);
    const next = observeAssistantReplies(baseline, ["t1:reply", "t2:reply"], false, 200);
    expect(next.unread).toEqual(["t2:reply"]);
    expect(next.pulseUntil).toBe(1600);
    expect(observeAssistantReplies(next, ["t1:reply", "t2:reply"], false, 20000)).toEqual(next);
    expect(observeAssistantReplies(next, ["t1:reply", "t2:reply"], true, 20000).unread).toEqual([]);
    expect(observeAssistantReplies(baseline, ["t1:reply", "t2:reply"], true, 300).unread).toEqual([]);
  });
  it("accepts only settled native final messages and uses logical item identities", () => {
    const detail = { messages: [{ role: "assistant", turnId: "t1", status: "completed", turnItems: [
      { type: "agent_message", phase: "final_answer", status: "completed", id: "revision-8", itemId: "answer", text: "Hello" },
      { type: "agent_message", phase: "commentary", status: "completed", itemId: "process", text: "Working" },
      { type: "reasoning", status: "completed", itemId: "thinking", text: "Reasoning" },
    ] }, { role: "assistant", turnId: "t2", status: "running", turnItems: [
      { type: "agent_message", phase: "final_answer", status: "completed", itemId: "answer", text: "Provisional" },
    ] }, { role: "assistant", turnId: "t3", status: "completed", metadata: { kind: "session_live_overlay" }, turnItems: [
      { type: "agent_message", phase: "final_answer", status: "completed", itemId: "answer", text: "Overlay" },
    ] }] } as SessionDetail;
    expect(assistantReplyIds(detail)).toEqual(["t1:answer"]);
  });
  it("retains only bounded IDs and synchronizes read acknowledgement between windows", () => {
    const identity = `test:${Math.random()}`;
    const store = assistantReplyStore(identity);
    store.observe(["old:answer"], false);
    store.observe(["old:answer", "new:answer"], false);
    expect(store.getSnapshot().unread).toEqual(["new:answer"]);
    const unsubscribe = store.subscribe(() => undefined);
    const key = `vibelution.assistant-replies.v1:${identity}`;
    const read = { ...store.getSnapshot(), unread: [], pulseUntil: 0 };
    localStorage.setItem(key, JSON.stringify(read));
    window.dispatchEvent(new StorageEvent("storage", { key }));
    expect(store.getSnapshot().unread).toEqual([]);
    store.observe(["old:answer", "new:answer"], false);
    expect(store.getSnapshot().pulseUntil).toBe(0);
    unsubscribe(); localStorage.removeItem(key);
    const bounded = observeAssistantReplies(EMPTY_REPLY_ACTIVITY, Array.from({ length: 300 }, (_, i) => `t:${i}`), false, 0);
    expect(bounded.known).toHaveLength(128);
  });
});
