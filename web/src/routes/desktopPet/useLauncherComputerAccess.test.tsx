// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail } from "../../api/types";
import type { ComputerState } from "../../api/types/personalAssistantComputer";
import { launcherAssistantComputer } from "../../api/launcherAssistantComputer";
import { computerAccessMatches, latestComputerTurn } from "./launcherComputerAccess";
import { useLauncherComputerAccess } from "./useLauncherComputerAccess";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const request = { id: "request-1", agentId: "assistant", sessionId: "session", turnId: "turn" };
const waiting: ComputerState = { available: true, status: "idle", message: "", grantId: null, window: null, pending: null, authorizationRequest: request };
const granted: ComputerState = { available: true, status: "ready", message: "", grantId: "grant", window: { selectionId: "w", title: "private", appName: "private" }, pending: null };
const detail = (): SessionDetail => ({
  id: "session", agentId: "assistant", status: "ready", activeTurnId: "", lastTurnTerminalTurnId: "turn", terminalReason: "success", queuedTurns: [],
  messages: [{ id: "user", role: "user" }, { id: "answer", role: "assistant", turnId: "turn", turnItems: [
    { id: "tool", type: "tool_call", toolName: "personal_assistant_computer_observe_tool", sessionId: "session", turnId: "turn" },
  ] }],
} as unknown as SessionDetail);
let container: HTMLDivElement, root: Root, client: QueryClient;
let state: ReturnType<typeof useLauncherComputerAccess>;
let props: Parameters<typeof useLauncherComputerAccess>[0];
function Harness() { state = useLauncherComputerAccess(props); return null; }
async function render() { await act(async () => { root.render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>); }); }
async function ready() { await act(async () => { await vi.waitFor(() => expect(state.request?.id).toBe(request.id)); }); }
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  vi.spyOn(launcherAssistantComputer, "state").mockResolvedValue(waiting);
  props = { detail: detail(), agentId: "assistant", reading: true, manualOpen: false, onCloseManual: vi.fn(), lang: "zh" };
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.restoreAllMocks(); });
describe("native computer authorization", () => {
  it("recognizes only an exact current observe call and an allowed native state", () => {
    const value = detail();
    expect(latestComputerTurn(value)).toBe("turn");
    expect(latestComputerTurn({ ...value, lastTurnTerminalTurnId: "old" })).toBe("");
    expect(computerAccessMatches(request, { ...value, agentId: "other" }, "assistant")).toBe(false);
    for (const terminalReason of ["stopped", "cancelled", "superseded", "failed", "unknown"]) {
      expect(latestComputerTurn({ ...value, terminalReason })).toBe("");
    }
    for (const status of ["stopping", "paused"]) {
      expect(latestComputerTurn({ ...value, activeTurnId: "turn", status })).toBe("");
    }
    const changed = { ...value.messages[1], turnItems: [{ ...value.messages[1].turnItems![0], toolName: "personal_assistant_computer_action_tool" }] };
    expect(latestComputerTurn({ ...value, messages: [value.messages[0], changed] })).toBe("");
    expect(latestComputerTurn({ ...value, queuedTurns: [{ id: "new" } as never] })).toBe("");
  });
  it("shows and dismisses an exact request without sending or enumerating windows", async () => {
    const windows = vi.spyOn(launcherAssistantComputer, "windows");
    await render(); await ready(); expect(state.show).toBe(true);
    await act(async () => state.onDismiss()); expect(state.show).toBe(false);
    props.reading = false; await render(); props.reading = true; await render(); await ready(); expect(state.show).toBe(false);
    expect(windows).not.toHaveBeenCalled();
  });
  it("restores existing grant controls even when the latest turn has no computer tool", async () => {
    vi.mocked(launcherAssistantComputer.state).mockResolvedValue(granted);
    props.detail = { ...detail(), messages: [] };
    await render(); await act(async () => { await vi.waitFor(() => expect(state.show).toBe(true)); });
    expect(state.request).toBeNull();
  });
  it("an explicit grant shows local controls and never submits a synthetic chat turn", async () => {
    await render(); await ready();
    await act(async () => state.onGranted(granted));
    expect(state.show).toBe(true);
    expect(state.notice).toContain("已授权");
    expect(state.request).toBeNull();
  });
  it("hides a cancelled request and stops reading while inactive", async () => {
    await render(); await ready();
    props.detail = { ...detail(), terminalReason: "cancelled" }; await render();
    expect(state.request).toBeNull(); expect(state.show).toBe(false);
    const count = vi.mocked(launcherAssistantComputer.state).mock.calls.length;
    props.reading = false; await render();
    expect(state.show).toBe(false); expect(launcherAssistantComputer.state).toHaveBeenCalledTimes(count);
  });
  it("captures only a bound grant before the RPC and completes that exact intent afterwards", async () => {
    const intent = { origin: { agentId: "assistant", sessionId: "session", turnId: "turn", userMessageId: "user", branchId: "" }, requestId: "same-request", toolIds: [], pendingToolIds: [] };
    const continuation = { capture: vi.fn(() => intent), complete: vi.fn(), cancel: vi.fn() };
    props.continuation = continuation;
    await render(); await ready();
    const finish = state.prepareContinuation("grant");
    expect(continuation.capture).toHaveBeenCalledOnce();
    expect(continuation.complete).not.toHaveBeenCalled();
    await act(async () => state.onGranted(granted));
    expect(state.request).toBeNull();
    finish?.(granted);
    expect(continuation.complete).toHaveBeenCalledWith(intent, expect.any(Function));
    expect(state.prepareContinuation("grant")).toBeUndefined();
  });
  it("keeps existing grant controls visible during a state read failure", async () => {
    vi.mocked(launcherAssistantComputer.state).mockResolvedValue(granted);
    await render(); await act(async () => { await vi.waitFor(() => expect(state.show).toBe(true)); });
    vi.mocked(launcherAssistantComputer.state).mockRejectedValue(new Error("temporary read failure"));
    props.detail = { ...detail(), activeTurnId: "new-turn", status: "running", messages: [...detail().messages, { id: "new", role: "user" } as never] };
    await render();
    await act(async () => { await client.refetchQueries({ queryKey: ["launcher-assistant", "computer-access"] }); });
    expect(state.request).toBeNull(); expect(state.show).toBe(true);
  });
  it("does not carry a grant into another native identity", async () => {
    vi.mocked(launcherAssistantComputer.state).mockResolvedValue(granted);
    await render(); await act(async () => { await vi.waitFor(() => expect(state.show).toBe(true)); });
    vi.mocked(launcherAssistantComputer.state).mockRejectedValue(new Error("read failure"));
    props.agentId = "other"; props.detail = { ...detail(), agentId: "other", id: "other-session" };
    await render();
    expect(state.show).toBe(false);
  });
});
