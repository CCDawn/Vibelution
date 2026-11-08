// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail } from "../../api/types";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";
import { loadLauncherComposer } from "./launcherAssistantComposerStorage";
import { CONTROL_CONTINUATION_MESSAGE } from "./launcherControlContinuation";
import type { LauncherControlContinuation } from "./useLauncherControlContinuation";

let surface: ConversationViewProps;
vi.mock("../../components/conversation/LazyConversationView", () => ({ LazyConversationView: (props: ConversationViewProps) => { surface = props; return <div>{props.composerPrecedingContent}</div>; } }));
vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
let root: Root, host: HTMLDivElement, client: QueryClient;
let control: LauncherControlContinuation | null;
let invoke: ReturnType<typeof vi.fn>;
let source: SessionDetail;
let failure = "";
const bind = (value: LauncherControlContinuation | null) => { control = value; };
const sends = () => invoke.mock.calls.filter(([payload]) => payload.operation === "send").map(([payload]) => payload);
async function settle() { await act(async () => new Promise(done => setTimeout(done, 20))); }
beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); localStorage.clear(); failure = "";
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP forbidden"); }));
  source = { id: "s", agentId: "a", status: "ready", terminalReason: "success", ledgerSeq: 10, activeLeafId: "h", activeBranchId: "b", lastTurnTerminalTurnId: "t",
    messages: [{ id: "u", role: "user", content: "original task", metadata: { turnId: "t" } },
      { id: "answer", role: "assistant", turnId: "t", status: "completed", turnItems: [] }] } as unknown as SessionDetail;
  invoke = vi.fn(async request => {
    switch (request.operation) {
      case "status": return { assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" }, settings: { ok: true, modelId: "model", displayName: "Assistant",
        preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" } } };
      case "detail": return source;
      case "config": return { language: "zh" };
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "send": {
        if (failure) throw new Error(failure);
        source = { ...source, status: "running", activeTurnId: "continued", terminalReason: "", ledgerSeq: 12, messages: [...source.messages,
          { id: "new-user", role: "user", content: request.message, timestamp: "", metadata: { turnId: "continued", clientSubmissionId: request.requestId } },
          { id: "new-assistant", role: "assistant", turnId: "continued", status: "running", timestamp: "", turnItems: [] }] };
        return { accepted: true, turnId: "continued" };
      }
      default: throw new Error(`Unexpected operation ${request.operation}`);
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={client}><LauncherAssistantRoute embedded navigationOwned onControlContinuationReady={bind} /></QueryClientProvider>));
  await settle(); await settle();
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); vi.unstubAllGlobals(); localStorage.clear(); });
describe("control continuation through native composer acceptance", () => {
  it("sends once with the bound snapshot and preserves a separate draft", async () => {
    await act(async () => surface.onComposerChange?.("next unsent task"));
    await act(async () => { const intent = control!.capture(); expect(intent).not.toBeNull(); control!.complete(intent); control!.complete(intent); });
    await settle();
    expect(sends()).toHaveLength(1);
    expect(sends()[0]).toMatchObject({ message: CONTROL_CONTINUATION_MESSAGE, controlContinuation: { agentId: "a", sessionId: "s", turnId: "t", headId: "h", ledgerSeq: 10 } });
    expect(surface.composerValue).toBe("next unsent task");
    expect(loadLauncherComposer("s", "embedded")?.outstanding).toBeNull();
  });
  it("clears an explicit identity refusal without locking or consuming the draft", async () => {
    failure = "Error invoking remote method 'assistant:request': Error: ASSISTANT_IDENTITY_INVALID";
    await act(async () => surface.onComposerChange?.("keep draft"));
    await act(async () => control!.complete(control!.capture())); await settle();
    expect(sends()).toHaveLength(1);
    expect(surface.composerValue).toBe("keep draft"); expect(surface.composerDisabled).toBe(false);
    expect(loadLauncherComposer("s", "embedded")?.outstanding).toBeNull();
  });
  it("retains an unknown outcome with its original snapshot and request ID", async () => {
    failure = "lost acknowledgement";
    await act(async () => control!.complete(control!.capture())); await settle();
    const original = sends()[0];
    expect(original).toBeDefined();
    expect(loadLauncherComposer("s", "embedded")?.outstanding).toMatchObject({ requestId: original.requestId, controlContinuation: original.controlContinuation, preserveDraft: true });
    await act(async () => { surface.onSubmit(); await vi.waitFor(() => expect(sends()).toHaveLength(2)); });
    expect(sends().every(request => request.requestId === original.requestId && JSON.stringify(request.controlContinuation) === JSON.stringify(original.controlContinuation))).toBe(true);
  });
});
