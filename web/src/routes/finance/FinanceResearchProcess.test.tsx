// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { FinanceResearchProcess } from "./FinanceResearchProcess";
import type { FinancialSessionView } from "./FinancialResearchBridge";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let cleanup = async () => {};
afterEach(async () => cleanup());
async function render(view: FinancialSessionView) {
  const node = document.createElement("div"); document.body.appendChild(node);
  const root = createRoot(node);
  cleanup = async () => { await act(async () => root.unmount()); node.remove(); };
  await act(async () => root.render(<FinanceResearchProcess view={view} activeTurn={null} zh onOpenChat={() => {}} />));
  return node;
}
const view: FinancialSessionView = { sessionId: "finance", title: "财报研究", status: "ready", busy: false, stopping: false, messages: [
  { role: "assistant", id: "answer", turnId: "native-turn", timestamp: "", status: "completed", turnItems: [{ type: "agent_message", id: "final", itemId: "final", version: 3, sessionId: "finance", turnId: "native-turn", revision: 1, sequence: 1, phase: "final_answer", status: "completed", text: "## 结论\n原生研究答复。" }] },
] };
describe("native financial process outcomes", () => {
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
});
