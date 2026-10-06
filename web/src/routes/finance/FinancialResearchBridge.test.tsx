// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionLlmModelOption, SessionLlmOptions, SessionModelSelection } from "../../api/types";
import { FinancialResearchBridgeContext, useFinancialResearchSessionBridge } from "./FinancialResearchBridge";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const change = vi.fn();
const focus = vi.fn();
const publish = vi.fn();
const submit = vi.fn();
const submitSelection = vi.fn();
const submitted = vi.fn();
let cleanup = async () => {};
afterEach(async () => { await cleanup(); vi.clearAllMocks(); });

function Consumer({ sessionId = "research", agentId = "finance", composerValue, busy = true, stopping = false, submitPending = false, transcriptPending = false, terminalReason }: {
  sessionId?: string; agentId?: string; composerValue?: string; busy?: boolean; stopping?: boolean; submitPending?: boolean; transcriptPending?: boolean; terminalReason?: string;
}) {
  useFinancialResearchSessionBridge({ sessionId, agentId, title: "研究", status: busy ? "running" : "ready", busy, stopping, terminalReason, lastTurnStatus: "ready", lastTurnTerminalTurnId: "native-turn", submitPending, transcriptPending, onComposerChange: change, onFocusComposer: focus, composerValue, onSubmit: submit });
  return null;
}
function value(sessionId = "research") {
  return { agentId: "finance", draftRequest: { id: 1, sessionId, text: "请核对财报证据" }, onSessionView: publish };
}

type NativeReadiness = { contextWindow: number; runtimeSelectable: boolean; providerHealthy: boolean };
function modelOption(modelId: string, modelRef: string, reasoningEffortValues: string[], readiness: Partial<NativeReadiness> = {}): SessionLlmModelOption & NativeReadiness {
  return {
    modelId, modelRef, label: modelId, model: modelId, providerId: "provider", providerLabel: "Provider", providerKind: "openai",
    apiKeyConfigured: true, missingApiKey: false, supportsReasoningEffort: true, reasoningEffortValues, reasoningEffortOptions: [],
    defaultReasoningEffort: reasoningEffortValues[0] ?? "", isDefault: modelRef === "provider/default",
    contextWindow: 1_000_000, runtimeSelectable: true, providerHealthy: true, ...readiness,
  };
}

function ModelConsumer({ initialSelection, options, optionsLoading = false, optionsError = false, sessionId = "research", agentId = "finance" }: {
  initialSelection: SessionModelSelection | null;
  options?: SessionLlmOptions;
  optionsLoading?: boolean;
  optionsError?: boolean;
  sessionId?: string;
  agentId?: string;
}) {
  const [selection, setSelection] = React.useState(initialSelection);
  const updateSelection = React.useCallback((_sessionId: string, next: SessionModelSelection | null) => setSelection(next), []);
  const onSubmit = React.useCallback(() => submitSelection(selection), [selection]);
  useFinancialResearchSessionBridge({
    sessionId, agentId, title: "研究", status: "ready", busy: false, stopping: false,
    onComposerChange: change, onFocusComposer: focus, composerValue: "请核对财报证据", onSubmit,
    sessionLlmOptions: options, sessionLlmOptionsLoading: optionsLoading, sessionLlmOptionsError: optionsError,
    turnModelSelection: selection, onTurnModelSelectionChange: updateSelection,
  });
  return <output data-testid="turn-model-selection">{JSON.stringify(selection)}</output>;
}

function financialLlmOptions(model: SessionLlmModelOption, alternate: SessionLlmModelOption): SessionLlmOptions {
  return { sessionId: "research", currentModelId: model.modelRef, currentReasoningEffort: model.defaultReasoningEffort, model, choices: [model, alternate] };
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

  it("publishes the native stopped outcome without converting ready to success", async () => {
    const root = setup();
    await act(async () => root.render(<FinancialResearchBridgeContext.Provider value={value()}><Consumer busy={false} terminalReason="stopped_by_user" /></FinancialResearchBridgeContext.Provider>));
    expect(publish).toHaveBeenCalledWith(expect.objectContaining({ status: "ready", terminalReason: "stopped_by_user", lastTurnStatus: "ready", lastTurnTerminalTurnId: "native-turn" }));
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

  it("submits with the requested model effort for this turn, then restores the prior pin", async () => {
    const root = setup();
    const previous = { modelId: "provider/alternate", reasoningEffort: "xhigh" };
    const options = financialLlmOptions(
      modelOption("default", "provider/default", ["minimal", "low", "medium", "high", "xhigh"]),
      modelOption("alternate", "provider/alternate", ["minimal", "low", "medium"]),
    );
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "basic" as const } };
    await act(async () => root.render(
      <React.StrictMode><FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={previous} options={options} />
      </FinancialResearchBridgeContext.Provider></React.StrictMode>,
    ));
    expect(submitSelection).toHaveBeenCalledExactlyOnceWith({ modelId: "provider/alternate", reasoningEffort: "low" });
    expect(document.querySelector('[data-testid="turn-model-selection"]')?.textContent).toBe(JSON.stringify(previous));
  });

  it("carries an explicit research model from the source view onto the target session", async () => {
    const root = setup();
    const requested = { modelId: "provider/alternate", reasoningEffort: "xhigh" };
    const options = financialLlmOptions(
      modelOption("default", "provider/default", ["minimal", "low", "medium", "high", "xhigh"]),
      modelOption("alternate", "provider/alternate", ["minimal", "low", "medium"]),
    );
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "basic" as const, modelSelection: requested } };
    await act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={null} options={options} />
      </FinancialResearchBridgeContext.Provider>,
    ));
    expect(submitSelection).toHaveBeenCalledExactlyOnceWith({ modelId: "provider/alternate", reasoningEffort: "low" });
    expect(document.querySelector('[data-testid="turn-model-selection"]')?.textContent).toBe("null");
  });

  it("rejects an explicit research model that the target session cannot execute", async () => {
    const root = setup();
    const requested = { modelId: "provider/alternate" };
    const options = financialLlmOptions(
      modelOption("default", "provider/default", ["minimal", "low", "medium"]),
      modelOption("alternate", "provider/alternate", ["low", "medium"], { contextWindow: 0 }),
    );
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "standard" as const, modelSelection: requested } };
    await act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={null} options={options} />
      </FinancialResearchBridgeContext.Provider>,
    ));
    expect(submitSelection).not.toHaveBeenCalled();
    expect(document.querySelector('[data-testid="turn-model-selection"]')?.textContent).toBe("null");
  });

  it("uses the selected model lowest effort when none is at or below the requested depth", async () => {
    const root = setup();
    const previous = { modelId: "provider/alternate", reasoningEffort: "high" };
    const options = financialLlmOptions(
      modelOption("default", "provider/default", ["minimal", "low", "medium", "high", "xhigh"]),
      modelOption("alternate", "provider/alternate", ["low", "medium"]),
    );
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "brief" as const } };
    await act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={previous} options={options} />
      </FinancialResearchBridgeContext.Provider>,
    ));
    expect(submitSelection).toHaveBeenCalledExactlyOnceWith({ modelId: "provider/alternate", reasoningEffort: "low" });
    expect(document.querySelector('[data-testid="turn-model-selection"]')?.textContent).toBe(JSON.stringify(previous));
  });

  it("waits for model choices before submitting the requested effort", async () => {
    const root = setup();
    const options = financialLlmOptions(
      modelOption("default", "provider/default", ["minimal", "low", "medium", "high", "xhigh"]),
      modelOption("alternate", "provider/alternate", ["minimal", "low", "medium", "high"]),
    );
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "detailed" as const } };
    const render = (optionsLoading: boolean) => act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={{ modelId: "provider/alternate" }} options={options} optionsLoading={optionsLoading} />
      </FinancialResearchBridgeContext.Provider>,
    ));
    await render(true);
    expect(submitSelection).not.toHaveBeenCalled();
    await render(false);
    expect(submitSelection).toHaveBeenCalledExactlyOnceWith({ modelId: "provider/alternate", reasoningEffort: "high" });
  });

  it("does not submit when native model capabilities cannot load", async () => {
    const root = setup();
    const previous = { modelId: "provider/alternate", reasoningEffort: "high" };
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "brief" as const } };
    await act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={previous} optionsError />
      </FinancialResearchBridgeContext.Provider>,
    ));
    expect(submitSelection).not.toHaveBeenCalled();
    expect(document.querySelector('[data-testid="turn-model-selection"]')?.textContent).toBe(JSON.stringify(previous));
  });

  it("does not let a ready per-turn model bypass an invalid assistant default", async () => {
    const root = setup();
    const previous = { modelId: "provider/alternate", reasoningEffort: "medium" };
    const options = financialLlmOptions(
      modelOption("default", "provider/default", ["minimal", "low", "medium"], { contextWindow: 0 }),
      modelOption("alternate", "provider/alternate", ["low", "medium"]),
    );
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "standard" as const } };
    await act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={previous} options={options} />
      </FinancialResearchBridgeContext.Provider>,
    ));
    expect(submitSelection).not.toHaveBeenCalled();
    expect(document.querySelector('[data-testid="turn-model-selection"]')?.textContent).toBe(JSON.stringify(previous));
  });

  it("waits for options belonging to the requested session and publishes native turn controls", async () => {
    const root = setup();
    const options = financialLlmOptions(
      modelOption("default", "provider/default", ["minimal", "low", "medium"]),
      modelOption("alternate", "provider/alternate", ["low", "medium"]),
    );
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "standard" as const } };
    const render = (sessionOptions: SessionLlmOptions) => act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={null} options={sessionOptions} />
      </FinancialResearchBridgeContext.Provider>,
    ));
    await render({ ...options, sessionId: "stale-session" });
    expect(submitSelection).not.toHaveBeenCalled();
    await render(options);
    expect(submitSelection).toHaveBeenCalledExactlyOnceWith({ modelId: "provider/default", reasoningEffort: "medium" });
    expect(publish).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "research",
      agentId: "finance",
      sessionLlmOptions: options,
      turnModelSelection: null,
      onTurnModelSelectionChange: expect.any(Function),
    }));
  });

  it("does not publish or submit model controls for another agent", async () => {
    const root = setup();
    const options = financialLlmOptions(
      modelOption("default", "provider/default", ["minimal", "low", "medium"]),
      modelOption("alternate", "provider/alternate", ["low", "medium"]),
    );
    const bridge = { ...value(), draftRequest: { ...value().draftRequest, submit: true, depth: "standard" as const } };
    await act(async () => root.render(
      <FinancialResearchBridgeContext.Provider value={bridge}>
        <ModelConsumer initialSelection={null} options={options} agentId="ordinary" />
      </FinancialResearchBridgeContext.Provider>,
    ));
    expect(submitSelection).not.toHaveBeenCalled();
    expect(publish).not.toHaveBeenCalled();
    expect(change).not.toHaveBeenCalled();
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
