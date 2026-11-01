import { describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import * as kernelApi from "../../api/kernel";
import type { AgentInstance, KernelTaskTimelinePayload, SessionDetail } from "../../api/types";
import type { AgentMessageRecord } from "../../components/agent-messages";
import { currentConversationMessages, kernelMessageRecord, mergeAgentMessageRecords, sessionMessageRecords } from "./agentMessageRecords";
import { readAgentMessageDirectory } from "./useAgentMessageRecords";

const agents = new Map([...[ ["sender", "发送助手"], ["reviewer", "审查助手"], ["tester", "测试助手"] ].map(([agentId, displayName]) => [agentId, { agentId, displayName, agentCode: agentId, avatarImageUrl: `/avatars/${agentId}.png` } as AgentInstance] as const)]);
function timeline(id = "event-1", wakeStatus = "started"): KernelTaskTimelinePayload {
  return {
    taskId: `task-${id}`, task: { taskId: `task-${id}`, status: "succeeded" }, event: { eventId: id, senderAgentId: "sender", sender: { id: "sender", displayName: "发送助手" }, recipients: ["reviewer"], createdAt: "2026-11-01T12:00:00Z",
      semanticPayload: { semanticType: "agent.message", payload: { content: "检查消息链路", summary: "相同标题" } }, metadata: { sourceSessionId: "source-session" } },
    deliveries: [{ targetAgentId: "reviewer", targetSessionId: "review-session", inboxMessageId: `inbox-${id}`, status: "delivered", wake: { wakeStatus, reason: wakeStatus === "failed" ? "SessionUnavailable: branch not started" : "" } }],
  } as unknown as KernelTaskTimelinePayload;
}
function record(id: string, extra: Partial<AgentMessageRecord> = {}): AgentMessageRecord {
  return { id, title: "相同标题", body: "相同内容", createdAt: "2026-11-01T12:00:00Z", sourceSessionId: "source-session", sender: { agentId: "sender", name: "发送助手" }, type: "request",
    recipients: [{ agentId: "reviewer", name: "审查助手", delivery: "delivered", handling: "unknown" }], ...extra };
}
function session(messages: unknown[]): SessionDetail { return { id: "source-session", agentId: "sender", messages } as unknown as SessionDetail; }

describe("cross-Agent message source projection", () => {
  it("keeps admission separate from actual processing and reuses directory identity", () => {
    const result = kernelMessageRecord(timeline(), agents)!;
    expect(result.sender.name).toBe("发送助手");
    expect(result.recipients[0]).toMatchObject({ name: "审查助手", delivery: "delivered", handling: "unknown", avatarImageUrl: "/avatars/reviewer.png" });
  });
  it("reports wake failure while preserving successful delivery and the concrete error", () => {
    const result = kernelMessageRecord(timeline("one", "failed"), agents)!;
    expect(result.recipients[0]).toMatchObject({ delivery: "delivered", handling: "wake_failed", error: "SessionUnavailable: branch not started" });
  });
  it.each(["skipped_policy_blocked", "skipped_archived_agent", "skipped_missing_agent", "skipped_no_direct_session"])("keeps permanent wake refusal %s visible as an exception", (status) => {
    const source = timeline("refused", status); source.deliveries[0].wake.reason = "target_unavailable";
    expect(kernelMessageRecord(source, agents)!.recipients[0]).toMatchObject({ delivery: "delivered", handling: "wake_failed", error: "target_unavailable" });
  });
  it("does not combine different sends with equal title, body, recipient or time", () => {
    expect(mergeAgentMessageRecords([record("one"), record("two")])).toHaveLength(2);
  });
  it("combines a kernel event and its tool return by exact event/inbox identity", () => {
    const detail = session([{ id: "turn", role: "assistant", turnId: "turn-1", timestamp: "2026-11-01T12:00:00Z", turnItems: [{ type: "tool_call", itemId: "call-1", toolName: "agent_message_tool", status: "completed",
      input: JSON.stringify({ content: "检查消息链路", target_agent: "reviewer", target_session: "review-session" }),
      output: JSON.stringify({ ok: true, status: "partial", messageId: "inbox-event-1", targetAgentId: "reviewer", targetSessionId: "review-session", inboxStatus: "recorded", wakeStatus: "failed", reason: "branch_offline", kernel: { kernelEventId: "event-1" } }) }] }]);
    const items = mergeAgentMessageRecords([kernelMessageRecord(timeline(), agents)!, ...sessionMessageRecords(detail, agents, new Map())]);
    expect(items).toHaveLength(1);
    expect(items[0].aliases).toContain("send:source-session:turn-1:call-1");
    expect(items[0].recipients[0]).toMatchObject({ delivery: "delivered", handling: "wake_failed", error: "branch_offline" });
  });
  it("keeps failed sends that never reached kernel and shows the actual diagnostic", () => {
    const detail = session([{ id: "turn", role: "assistant", turnId: "turn-1", timestamp: "2026-11-01T12:00:00Z", turnItems: [{ type: "tool_call", itemId: "call-1", toolName: "agent_message_tool", status: "completed", input: JSON.stringify({ content: "hello", target_session: "missing" }), output: JSON.stringify({ ok: false, error: "ValueError", message: "Target session does not exist" }) }] }]);
    expect(sessionMessageRecords(detail, agents, new Map())[0].recipients[0]).toMatchObject({ delivery: "failed", error: "ValueError: Target session does not exist" });
  });
  it("links only the explicit original ID and recipient; never matches a title", () => {
    const original = record("one", { aliases: ["inbox-one"], recipients: [...record("one").recipients, { agentId: "tester", name: "测试助手", delivery: "delivered", handling: "queued" }] });
    const reply = record("reply-one", { sender: { agentId: "reviewer", name: "审查助手" }, replyToId: "inbox-one", type: "reply", sourceSessionId: "review-session",
      recipients: [{ agentId: "sender", name: "发送助手", delivery: "delivered", handling: "unknown" }] });
    const result = mergeAgentMessageRecords([original, record("two"), reply]);
    expect(result.find((item) => item.id === "one")!.recipients.map((item) => item.handling)).toEqual(["replied", "queued"]);
    expect(result.find((item) => item.id === "two")!.recipients[0].handling).toBe("unknown");
    expect(result.find((item) => item.id === "reply-one")!.replyToId).toBe("one");
    expect(currentConversationMessages(result, "source-session").map((item) => item.id)).toContain("reply-one");
    expect(original.recipients[0].handling).toBe("unknown");
  });
  it.each(["failed", "sending", "unknown", "revoked"] as const)("does not mark the request replied when the reply delivery is %s", (delivery) => {
    const reply = record("reply-one", { sender: { agentId: "reviewer", name: "审查助手" }, type: "reply", replyToId: "one",
      recipients: [{ agentId: "sender", name: "发送助手", delivery, handling: "unknown" }] });
    const result = mergeAgentMessageRecords([record("one"), reply]);
    expect(result.find((item) => item.id === "one")!.recipients[0].handling).toBe("unknown");
    expect(result.find((item) => item.id === "reply-one")!.replyToId).toBe("one");
  });
  it("does not mark the request replied for a reply delivered to another Agent", () => {
    const reply = record("reply-one", { sender: { agentId: "reviewer", name: "审查助手" }, type: "reply", replyToId: "one" });
    expect(mergeAgentMessageRecords([record("one"), reply]).find((item) => item.id === "one")!.recipients[0].handling).toBe("unknown");
  });
  it("clears an old wake error after a confirmed reply even without a receiver journal window", () => {
    const origin = record("one", { recipients: [{ agentId: "reviewer", name: "审查助手", delivery: "delivered", handling: "wake_failed", error: "old wake failure" }] });
    const reply = record("reply-one", { sender: { agentId: "reviewer", name: "审查助手" }, type: "reply", replyToId: "one",
      recipients: [{ agentId: "sender", name: "发送助手", delivery: "delivered", handling: "unknown" }] });
    expect(mergeAgentMessageRecords([origin, reply]).find((item) => item.id === "one")!.recipients[0]).toMatchObject({ handling: "replied", error: undefined });
  });
  it("reads native automatic replies without inventing missing kind/messageId fields", () => {
    const detail = session([{ id: "native-row", nodeId: "journal-node-1", role: "user", timestamp: "2026-11-01T12:01:00Z", content: "检查完成", metadata: { sourceSurface: "agent_inbox_reply", sourceAgentId: "reviewer", sourceSessionId: "review-session", sourceTurnId: "review-turn", replyToMessageId: "inbox-one" } }]);
    const reply = sessionMessageRecords(detail, agents, new Map())[0];
    const result = mergeAgentMessageRecords([record("one", { aliases: ["inbox-one"] }), reply]);
    expect(reply).toMatchObject({ type: "reply", replyToId: "inbox-one", body: "检查完成", sender: { agentId: "reviewer" } });
    expect(result.find((item) => item.id === "one")!.recipients[0].handling).toBe("replied");
  });
  it("treats consumed journal evidence as received rather than processing or read", () => {
    const detail = session([{ id: "native-row", role: "user", timestamp: "2026-11-01T12:01:00Z", content: "hello", metadata: { kind: "agent_inbox_message", messageId: "inbox-one", sourceAgentId: "reviewer", targetAgentId: "sender" } }]);
    expect(sessionMessageRecords(detail, agents, new Map())[0].recipients[0]).toMatchObject({ delivery: "delivered", handling: "received" });
  });
  it("excludes ordinary user text and unrelated kernel events", () => {
    expect(sessionMessageRecords(session([{ role: "user", id: "ordinary", content: "普通聊天", metadata: {} }]), agents, new Map())).toEqual([]);
    const unrelated = timeline(); unrelated.event.semanticPayload.semanticType = "task.run";
    expect(kernelMessageRecord(unrelated, agents)).toBeNull();
  });
  it.each(["queued", "wake_failed"] as const)("keeps journal receipt evidence ahead of stale %s in either cache order", (handling) => {
    const received = record("inbox-one", { recipients: [{ agentId: "reviewer", name: "审查助手", delivery: "delivered", handling: "received" }] });
    const stale = record("one", { aliases: ["inbox-one"], recipients: [{ agentId: "reviewer", name: "审查助手", delivery: "failed", handling, error: "old wake failure" }] });
    for (const inputs of [[received, stale], [stale, received]]) {
      expect(mergeAgentMessageRecords(inputs)[0].recipients[0]).toMatchObject({ delivery: "delivered", handling: "received", error: undefined });
    }
  });
  it("does not restore a recalled envelope from an older receiver journal receipt", () => {
    const revoked = record("bus-event", { aliases: ["inbox-one"], type: "notification", sourceEventId: "bus-event", body: "这条消息已撤回。", recipients: [{ agentId: "reviewer", name: "审查助手", delivery: "revoked", handling: "unknown" }] });
    const received = record("inbox-one", { body: "旧的原始正文", recipients: [{ agentId: "reviewer", name: "审查助手", delivery: "delivered", handling: "received" }] });
    const merged = mergeAgentMessageRecords([revoked, received])[0];
    expect(merged.body).toBe("这条消息已撤回。");
    expect(merged.type).toBe("notification");
    expect(merged.recipients[0].delivery).toBe("revoked");
  });
});

describe("existing kernel directory transport", () => {
  it("refreshes a running cached timeline when the directory reports it finished", async () => {
    const list = vi.spyOn(kernelApi, "listKernelTasks").mockResolvedValue({ tasks: [{ taskId: "task-one", status: "succeeded" }], limit: 30 } as never);
    const final = timeline("one");
    const get = vi.spyOn(kernelApi, "getKernelTaskTimeline").mockResolvedValue(final);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["kernel", "tasks", "task-one", "timeline"], { ...final, task: { ...final.task, status: "running" } });
    try {
      const result = await readAgentMessageDirectory(client, 30);
      expect(get).toHaveBeenCalledTimes(1);
      expect(result.timelines[0].task.status).toBe("succeeded");
      await readAgentMessageDirectory(client, 30);
      expect(get).toHaveBeenCalledTimes(1);
    } finally { client.clear(); list.mockRestore(); get.mockRestore(); }
  });
  it("bounds concurrent reads and caches terminal snapshots", async () => {
    const list = vi.spyOn(kernelApi, "listKernelTasks").mockResolvedValue({ tasks: Array.from({ length: 9 }, (_, index) => ({ taskId: String(index), status: "succeeded" })), limit: 30 } as never);
    let active = 0, peak = 0;
    const get = vi.spyOn(kernelApi, "getKernelTaskTimeline").mockImplementation(async (id) => {
      active += 1; peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 1)); active -= 1;
      return timeline(id);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      const result = await readAgentMessageDirectory(client, 30);
      await readAgentMessageDirectory(client, 30);
      expect(result).toMatchObject({ scanned: 9, unavailable: 0, hasMore: false });
      expect(peak).toBeLessThanOrEqual(4); expect(get).toHaveBeenCalledTimes(9);
    } finally { client.clear(); list.mockRestore(); get.mockRestore(); }
  });
  it("retains readable records and reports a partial source failure", async () => {
    const list = vi.spyOn(kernelApi, "listKernelTasks").mockResolvedValue({ tasks: [{ taskId: "one", status: "completed" }, { taskId: "bad", status: "completed" }], limit: 30 } as never);
    const get = vi.spyOn(kernelApi, "getKernelTaskTimeline").mockImplementation(async (id) => { if (id === "bad") throw new Error("source unavailable"); return timeline(id); });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      const result = await readAgentMessageDirectory(client, 30);
      expect(result.unavailable).toBe(1); expect(result.timelines).toHaveLength(1);
    } finally { client.clear(); list.mockRestore(); get.mockRestore(); }
  });
});
