// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinancialResearchBridgeContext, useFinancialResearchSessionBridge } from "./FinancialResearchBridge";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const change = vi.fn();
const focus = vi.fn();
const publish = vi.fn();
const submit = vi.fn();
const submitted = vi.fn();
let cleanup = async () => {};
afterEach(async () => { await cleanup(); vi.clearAllMocks(); });

function Consumer({ sessionId = "research", agentId = "finance", composerValue, busy = true, stopping = false, submitPending = false, transcriptPending = false }: {
  sessionId?: string; agentId?: string; composerValue?: string; busy?: boolean; stopping?: boolean; submitPending?: boolean; transcriptPending?: boolean;
}) {
  useFinancialResearchSessionBridge({ sessionId, agentId, title: "研究", status: busy ? "running" : "ready", busy, stopping, submitPending, transcriptPending, onComposerChange: change, onFocusComposer: focus, composerValue, onSubmit: submit });
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

  it("submits once in StrictMode only after the exact native draft commits", async () => {
    const root = setup();
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true }, onDraftSubmitted: submitted };
    const render = (composerValue: string) => act(async () => root.render(
      <React.StrictMode><FinancialResearchBridgeContext.Provider value={bridge}>
        <Consumer busy={false} composerValue={composerValue} />
      </FinancialResearchBridgeContext.Provider></React.StrictMode>,
    ));
    await render("earlier draft");
    expect(change).toHaveBeenCalledExactlyOnceWith("请核对财报证据");
    expect(submit).not.toHaveBeenCalled();
    await render(bridge.draftRequest.text);
    await render(bridge.draftRequest.text);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submitted).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("waits while native submission is busy, stopping or pending", async () => {
    const root = setup();
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true } };
    const render = (props: { busy?: boolean; stopping?: boolean; submitPending?: boolean; transcriptPending?: boolean }) => act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <Consumer composerValue={bridge.draftRequest.text} busy={false} {...props} />
      </FinancialResearchBridgeContext.Provider>,
    ));
    await render({ busy: true });
    await render({ stopping: true });
    await render({ submitPending: true });
    await render({ transcriptPending: true });
    expect(submit).not.toHaveBeenCalled();
    await render({});
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("does not submit a prepared request after switching Agent or Session", async () => {
    const root = setup();
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true } };
    const render = (props: { agentId?: string; sessionId?: string; composerValue?: string }) => act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}><Consumer busy={false} {...props} /></FinancialResearchBridgeContext.Provider>,
    ));
    await render({ composerValue: "" });
    await render({ agentId: "ordinary", composerValue: bridge.draftRequest.text });
    await render({ sessionId: "another", composerValue: bridge.draftRequest.text });
    expect(submit).not.toHaveBeenCalled();
  });
});
