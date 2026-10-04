// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinancialResearchBridgeContext, useFinancialResearchSessionBridge } from "./FinancialResearchBridge";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const change = vi.fn();
const focus = vi.fn();
const publish = vi.fn();
let cleanup = async () => {};
afterEach(async () => { await cleanup(); vi.clearAllMocks(); });

function Consumer({ sessionId = "research", agentId = "finance" }: { sessionId?: string; agentId?: string }) {
  useFinancialResearchSessionBridge({ sessionId, agentId, title: "研究", status: "running", busy: true, stopping: false, onComposerChange: change, onFocusComposer: focus });
  return null;
}
function value(sessionId = "research") {
  return { agentId: "finance", draftRequest: { id: 1, sessionId, text: "请核对财报证据" }, onSessionView: publish };
}
function setup() {
  const node = document.createElement("div"); document.body.appendChild(node);
  const root = createRoot(node);
  cleanup = async () => { await act(async () => root.unmount()); node.remove(); };
  return root;
}
describe("financial native composer bridge", () => {
  it("leaves ordinary chat untouched without a financial provider", async () => {
    const root = setup();
    await act(async () => root.render(<Consumer />));
    expect(change).not.toHaveBeenCalled(); expect(focus).not.toHaveBeenCalled(); expect(publish).not.toHaveBeenCalled();
  });
  it("consumes a draft once across effect replays and publishes native running state", async () => {
    const root = setup();
    await act(async () => root.render(<React.StrictMode><FinancialResearchBridgeContext.Provider value={value()}><Consumer /></FinancialResearchBridgeContext.Provider></React.StrictMode>));
    expect(change).toHaveBeenCalledExactlyOnceWith("请核对财报证据");
    expect(focus).toHaveBeenCalledExactlyOnceWith("research");
    expect(publish).toHaveBeenCalledWith(expect.objectContaining({ sessionId: "research", busy: true }));
  });
  it("waits for the requested session and refuses another agent", async () => {
    const root = setup();
    await act(async () => root.render(<FinancialResearchBridgeContext.Provider value={value()}><Consumer sessionId="other" /></FinancialResearchBridgeContext.Provider>));
    expect(change).not.toHaveBeenCalled();
    await act(async () => root.render(<FinancialResearchBridgeContext.Provider value={value()}><Consumer agentId="ordinary" /></FinancialResearchBridgeContext.Provider>));
    expect(change).not.toHaveBeenCalled();
    await act(async () => root.render(<FinancialResearchBridgeContext.Provider value={value()}><Consumer /></FinancialResearchBridgeContext.Provider>));
    expect(change).toHaveBeenCalledExactlyOnceWith("请核对财报证据");
  });
});
