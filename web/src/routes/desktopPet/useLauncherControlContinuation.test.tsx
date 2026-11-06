// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail } from "../../api/types";
import { useLauncherControlContinuation } from "./useLauncherControlContinuation";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, container: HTMLDivElement;
let result: ReturnType<typeof useLauncherControlContinuation>;
let props: Parameters<typeof useLauncherControlContinuation>[0];
function Harness() { result = useLauncherControlContinuation(props); return null; }
async function render() { await act(async () => root.render(<Harness />)); }
beforeEach(() => {
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  const detail = { id: "s", agentId: "a", status: "ready", terminalReason: "success", ledgerSeq: 12, activeLeafId: "head",
    lastTurnTerminalTurnId: "t", messages: [{ id: "u", role: "user", metadata: { turnId: "t" } }, { id: "a", role: "assistant", turnId: "t", turnItems: [] }] } as SessionDetail;
  props = { context: { detail, agentId: "a", blocked: false }, readCurrent: () => props.context, submit: vi.fn().mockResolvedValue(true) };
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
describe("operator completion hook", () => {
  it("does not add a second turn when the original resumes tools before the operator RPC returns", async () => {
    props.context.detail = { ...props.context.detail!, status: "running", activeTurnId: "t", terminalReason: "" };
    await render(); let captured: ReturnType<typeof result.capture>;
    await act(async () => { captured = result.capture(); });
    props.context = { ...props.context, detail: { ...props.context.detail!, status: "ready", activeTurnId: "", terminalReason: "success",
      messages: [props.context.detail!.messages[0], { ...props.context.detail!.messages[1], turnItems: [
        { id: "tool.rev2", itemId: "resumed-tool", type: "tool_call", sessionId: "s", turnId: "t", status: "completed" } as never,
      ] }] } }; await render();
    await act(async () => result.complete(captured!));
    expect(props.submit).not.toHaveBeenCalled();
  });
  it("revokes a pending or in-flight continuation on another takeover", async () => {
    props.context.detail = { ...props.context.detail!, status: "running", activeTurnId: "t", terminalReason: "" };
    await render(); let captured: ReturnType<typeof result.capture>;
    await act(async () => { captured = result.capture(); result.complete(captured); result.cancel(); });
    props.context = { ...props.context, detail: { ...props.context.detail!, status: "ready", activeTurnId: "", terminalReason: "success" } }; await render();
    await act(async () => result.complete(captured!));
    expect(props.submit).not.toHaveBeenCalled();
  });
  it("waits until the exact native worker releases its terminal owner", async () => {
    props.context.detail = { ...props.context.detail!, activeTurnId: "t" };
    await render(); let captured: ReturnType<typeof result.capture>;
    await act(async () => { captured = result.capture(); result.complete(captured); });
    expect(props.submit).not.toHaveBeenCalled();
    props.context = { ...props.context, detail: { ...props.context.detail!, activeTurnId: "" } }; await render();
    expect(props.submit).toHaveBeenCalledOnce();
  });
  it("checks live operator ownership before submitting even if the cancel effect has not run", async () => {
    let allowed = true;
    props.context.detail = { ...props.context.detail!, status: "running", activeTurnId: "t", terminalReason: "" };
    await render();
    await act(async () => result.complete(result.capture(), () => allowed));
    allowed = false;
    props.context = { ...props.context, detail: { ...props.context.detail!, status: "ready", activeTurnId: "", terminalReason: "success" } }; await render();
    expect(props.submit).not.toHaveBeenCalled();
  });
  it("polls never send; only a successful explicit completion submits once", async () => {
    await render(); await render(); expect(props.submit).not.toHaveBeenCalled();
    const captured = result.capture();
    await act(async () => { result.complete(captured); result.complete(captured); });
    expect(props.submit).toHaveBeenCalledTimes(1);
    expect(vi.mocked(props.submit).mock.calls[0][0]).toMatchObject({ requestId: captured!.requestId, preserveDraft: true });
    await render(); expect(props.submit).toHaveBeenCalledTimes(1);
  });
  it("does not send when the RPC completes after identity changed", async () => {
    await render(); const captured = result.capture();
    props.context = { ...props.context, agentId: "other" }; await render();
    await act(async () => result.complete(captured));
    expect(props.submit).not.toHaveBeenCalled();
  });
  it("waits for the same running turn but cancels on stop", async () => {
    props.context.detail = { ...props.context.detail!, status: "running", activeTurnId: "t", terminalReason: "" };
    await render(); const captured = result.capture();
    await act(async () => result.complete(captured)); expect(props.submit).not.toHaveBeenCalled();
    props.context = { ...props.context, detail: { ...props.context.detail!, status: "ready", activeTurnId: "", terminalReason: "stopped" } }; await render();
    props.context = { ...props.context, detail: { ...props.context.detail!, terminalReason: "success" } }; await render();
    expect(props.submit).not.toHaveBeenCalled();
  });
  it("sends through existing recovery once after natural completion; false never creates another request", async () => {
    props.submit = vi.fn().mockResolvedValue(false);
    props.context.detail = { ...props.context.detail!, status: "running", activeTurnId: "t", terminalReason: "" };
    await render(); const captured = result.capture();
    await act(async () => result.complete(captured));
    props.context = { ...props.context, detail: { ...props.context.detail!, status: "ready", activeTurnId: "", terminalReason: "success", ledgerSeq: 20 } }; await render();
    await render(); expect(props.submit).toHaveBeenCalledTimes(1);
  });
});
