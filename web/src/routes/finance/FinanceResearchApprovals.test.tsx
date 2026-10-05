// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceResearchApprovals, type FinanceApprovalTurnRef } from "./FinanceResearchApprovals";
import type { SessionToolApprovalRequest } from "../../api/types";

const api = vi.hoisted(() => ({ list: vi.fn(), decide: vi.fn() }));
vi.mock("../../api/chat", () => ({ listPendingSessionToolApprovals: api.list, resolveSessionToolApprovalDecision: api.decide }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let node: HTMLDivElement, root: Root, client: QueryClient;
const ref: FinanceApprovalTurnRef = { role: "market", sessionId: "market-session", turnId: "market-turn", agentId: "market-agent", symbol: "sh600519" };
function request(overrides: Partial<SessionToolApprovalRequest> = {}): SessionToolApprovalRequest {
  return { requestId: "approval", sessionId: ref.sessionId, turnId: ref.turnId, agentId: ref.agentId!, callId: "call", toolName: "financial_market_snapshot_tool",
    approval: "on_request", risk: "network", argumentsHash: "hash", argumentSummary: { symbol: "sh600519" }, sessionGrantScope: {}, decisionFingerprint: "fingerprint",
    configRevision: 1, configHash: "config", permissionPreset: "request_approval", availableDecisions: ["accept", "decline", "acceptForSession"],
    createdAt: "2026-10-06T00:00:00Z", status: "pending", decision: null, resolvedAt: null, ...overrides };
}
async function settle() { await act(async () => new Promise((done) => setTimeout(done, 15))); }
async function render(turns = [ref], owner = "owner") {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceResearchApprovals assistantAgentId={owner} turns={turns} zh /></QueryClientProvider>));
  await settle();
}
function button(title: string) { return [...node.querySelectorAll("button")].find((b) => b.title.includes(title))!; }
beforeEach(() => { vi.resetAllMocks(); node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node); client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); api.list.mockResolvedValue([]); });
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });

it("shows only native pending approvals for the exact current Session, Turn and Agent", async () => {
  api.list.mockResolvedValue([request({ requestId: "older", turnId: "older-turn" }), request({ requestId: "other", sessionId: "other-session" }),
    request({ requestId: "wrong-owner", agentId: "other-agent" }), request({ requestId: "expired", status: "expired" }), request()]);
  await render();
  expect(node.textContent).toContain("sh600519 · 行情等待授权 · 1 项");
  expect(node.textContent).toContain("查询行情与K线"); expect(node.textContent).not.toContain("始终");
  expect(button("仅批准本次")).toBeDefined(); expect(button("本会话始终")).toBeUndefined();
  api.list.mockResolvedValue([]); api.decide.mockResolvedValue(request({ status: "accepted" }));
  await act(async () => button("仅批准本次").click()); await settle();
  expect(api.decide).toHaveBeenCalledWith(request(), "accept"); expect(node.querySelector('[role="dialog"]')).toBeNull();
});

it("serializes one decision and then shows the next analyst without approving it", async () => {
  const newsRef = { ...ref, role: "news" as const, sessionId: "news-session", turnId: "news-turn", agentId: "news-agent" };
  const news = request({ ...newsRef, requestId: "news", createdAt: "2026-10-06T00:00:01Z" });
  api.list.mockImplementation(async (sid: string) => sid === ref.sessionId ? [request()] : [news]);
  let finish!: (value: SessionToolApprovalRequest) => void;
  api.decide.mockImplementation(() => new Promise<SessionToolApprovalRequest>((done) => { finish = done; }));
  await render([ref, newsRef]);
  const yes = button("仅批准本次");
  await act(async () => { yes.click(); yes.click(); });
  expect(api.decide).toHaveBeenCalledTimes(1); expect(node.querySelectorAll('[role="dialog"]')).toHaveLength(1);
  api.list.mockImplementation(async (sid: string) => sid === ref.sessionId ? [] : [news]);
  await act(async () => finish(request({ status: "accepted" }))); await settle();
  expect(node.textContent).toContain("新闻等待授权 · 1 项"); expect(api.decide).toHaveBeenCalledTimes(1);
});

it("declines only the selected call and hides it after native readback", async () => {
  api.list.mockResolvedValue([request()]); await render();
  api.list.mockResolvedValue([]); api.decide.mockResolvedValue(request({ status: "declined" }));
  await act(async () => button("拒绝本次").click()); await settle();
  expect(api.decide).toHaveBeenCalledWith(request(), "decline"); expect(node.textContent).toBe("");
});

it("does not carry late decision failures into another research identity", async () => {
  api.list.mockResolvedValue([request()]);
  let reject!: (error: Error) => void;
  api.decide.mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
  await render(); await act(async () => button("仅批准本次").click());
  await render([], "another-owner");
  await act(async () => reject(new Error("old decision failed"))); await settle();
  expect(node.textContent).not.toContain("old decision failed"); expect(node.querySelector('[role="dialog"]')).toBeNull();
});

it("shows approval read failures with a retry instead of pretending there are none", async () => {
  api.list.mockRejectedValueOnce(new Error("unavailable")); await render();
  expect(node.textContent).toContain("待授权查询暂不可用");
  await act(async () => [...node.querySelectorAll("button")].find((b) => b.textContent?.includes("重试"))!.click()); await settle();
  expect(node.textContent).toBe("");
});
