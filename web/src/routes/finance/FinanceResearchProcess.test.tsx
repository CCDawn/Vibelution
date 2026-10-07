// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinanceResearchProcess } from "./FinanceResearchProcess";
import type { FinancialSessionView } from "./FinancialResearchBridge";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let cleanup = async () => {};
afterEach(async () => cleanup());
async function render(view: FinancialSessionView, props: Partial<React.ComponentProps<typeof FinanceResearchProcess>> = {}) {
  const node = document.createElement("div"); document.body.appendChild(node);
  const root = createRoot(node);
  cleanup = async () => { await act(async () => root.unmount()); node.remove(); };
  await act(async () => root.render(<FinanceResearchProcess view={view} activeTurn={null} zh onOpenChat={() => {}} {...props} />));
  return node;
}
const view: FinancialSessionView = { sessionId: "finance", title: "财报研究", status: "ready", busy: false, stopping: false, messages: [
  { role: "assistant", id: "answer", turnId: "native-turn", timestamp: "", status: "completed", turnItems: [{ type: "agent_message", id: "final", itemId: "final", version: 3, sessionId: "finance", turnId: "native-turn", revision: 1, sequence: 1, phase: "final_answer", status: "completed", text: "## 结论\n原生研究答复。" }] },
] };
describe("native financial process outcomes", () => {
  it("keeps the research title and current status on one compact line", async () => {
    const node = await render(view);
    const title = node.querySelector<HTMLElement>('p[title="财报研究"]');
    const status = node.querySelector('[role="status"]');
    expect(title?.parentElement?.contains(status)).toBe(true);
  });
  it.each([
    ["failed_runtime", "failed_provider", "研究未完成"],
    ["ready", "stopped_by_user", "已停止"],
    ["needs_continue", "needs_continue", "待继续"],
  ])("does not show expired approvals after native %s", async (status, terminalReason, label) => {
    const node = await render({ ...view, status, terminalReason, approvalPending: true, lastTurnTerminalTurnId: "native-turn" });
    expect(node.querySelector('[role="status"]')?.textContent).toBe(label);
    expect(node.textContent).not.toContain("查看并授权");
  });
  it("keeps current approvals visible while a new native Turn is running", async () => {
    const node = await render({ ...view, status: "running", busy: true, approvalPending: true });
    expect(node.querySelector('[role="status"]')?.textContent).toBe("等待授权");
    expect(node.textContent).toContain("查看并授权");
  });
  it("shows a stop icon and title while the native session is stopping", async () => {
    const node = await render({ ...view, status: "stopping", stopping: true, busy: true });
    const status = node.querySelector<HTMLElement>('[role="status"]');
    expect(status?.textContent).toBe("正在停止");
    expect(status?.title).toBe("正在停止");
    expect(status?.querySelector("svg")?.getAttribute("class")).toMatch(/stop-circle|circle-stop/);
  });
  it("keeps the complete provider error readable in the compact panel", async () => {
    const error = `${"Provider failed while assembling the report. ".repeat(3)}Full diagnostic tail.`;
    const node = await render({ ...view, error });
    expect(node.querySelector('[role="status"]')?.textContent).toBe("研究未完成");
    expect(node.textContent).toContain(error);
  });
  it.each([["partial", "部分结果"], ["fallback", "使用备用来源"], ["unavailable", "数据不可用"], ["degraded", "降级完成"]])("keeps completed %s tool outcomes visible", async (semanticStatus, label) => {
    const turn = view.messages[0];
    if (turn.role !== "assistant") throw new Error("Expected assistant fixture");
    const node = await render(view, { activeTurn: { ...turn, turnItems: [
      { type: "tool_call", id: "market", itemId: "market", version: 3, sessionId: "finance", turnId: "native-turn", revision: 1, sequence: 1, callId: "market", toolName: "financial_market_snapshot_tool", status: "completed", semanticStatus },
    ] } });
    expect(node.querySelector("ol")?.textContent).toContain(label);
    expect(node.querySelector("ol")?.textContent).not.toContain("已完成");
    expect(node.querySelector('[role="status"]')?.textContent).toBe("已完成 · 结果需核对");
  });
  it("shows a stopped research even when the native message is completed", async () => {
    const node = await render({ ...view, error: "Earlier provider error", terminalReason: "stopped_by_user", lastTurnTerminalTurnId: "native-turn" });
    expect(node.querySelector('[role="status"]')?.textContent).toBe("已停止");
    expect(node.textContent).not.toContain("Earlier provider error");
  });
  it("shows native continuation requirements instead of completion", async () => {
    const node = await render({ ...view, status: "needs_continue", terminalReason: "needs_continue" });
    expect(node.querySelector('[role="status"]')?.textContent).toBe("待继续");
  });
  it("does not claim no research was started after a successful no-tool turn", async () => {
    const node = await render({ ...view, terminalReason: "success" });
    expect(node.querySelector('[role="status"]')?.textContent).toBe("已完成");
    expect(node.textContent).toContain("本轮未调用外部工具");
    expect(node.textContent).not.toContain("尚未开始研究");
  });
  it("offers market activation only when supplied and disables it during a write", async () => {
    const enable = vi.fn();
    const node = await render(view, { onEnableMarket: enable, marketPending: true });
    const button = Array.from(node.querySelectorAll("button")).find((item) => item.textContent?.includes("启用行情查询"));
    expect(button?.disabled).toBe(true);
    await act(async () => button?.click());
    expect(enable).not.toHaveBeenCalled();
  });
  it("labels the canonical market call using native tool state", async () => {
    const turn = view.messages[0];
    if (turn.role !== "assistant") throw new Error("Expected assistant fixture");
    const node = await render(view, { activeTurn: { ...turn, turnItems: [{
      type: "tool_call", id: "market", itemId: "market", version: 3, sessionId: "finance", turnId: "native-turn",
      revision: 1, sequence: 1, toolName: "financial_market_snapshot_tool", status: "failed", title: "financial_market_snapshot_tool",
    }] } });
    expect(node.querySelector("ol")?.textContent).toContain("查询行情与K线");
    expect(node.querySelector("ol")?.textContent).toContain("失败");
    expect(node.textContent).not.toContain("启用行情查询");
  });
});
