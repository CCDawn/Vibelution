// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { useChatContinueTurn } from "./useChatContinueTurn";
import type { ChatComposerTurnMutations } from "./useChatComposerTurnMutations";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => { if (root) await act(() => root.unmount()); document.body.innerHTML = ""; });
const detail = { id: "session-a", agentId: "agent-a", activeLeafId: "head-a", ledgerSeq: 12,
  lastTurnTerminalTurnId: "turn-a", terminalReason: "stopped_by_user", currentPhase: "ready" } as SessionDetail;
const gate = () => false;

async function mount(mutateAsync: ReturnType<typeof vi.fn>, overrides: Record<string, unknown> = {}) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.session("session-a"), detail);
  let continuation!: () => void;
  function Harness() {
    continuation = useChatContinueTurn({ queryClient: client, activeSessionId: "session-a", detail,
      activeDraftEffective: "", hasAttachments: false, hasReferences: false, blocked: false,
      isModelParametersSavePending: gate,
      submitTurnMutation: { mutateAsync } as unknown as ChatComposerTurnMutations["submitTurnMutation"],
      mentalModelEnabled: false, runtimeStatusEnabled: true, ...overrides });
    return <button onClick={() => continuation()}>Continue</button>;
  }
  const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(() => root.render(<Harness />));
  return { client, click: async () => act(() => continuation()) };
}

describe("native Play continuation", () => {
  it("double-clicks once and submits a new visible continuation without replaying or borrowing attachments", async () => {
    let finish!: (value: unknown) => void;
    const mutateAsync = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
    const view = await mount(mutateAsync);
    await view.click(); await view.click();
    expect(mutateAsync).toHaveBeenCalledOnce();
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({ sessionId: "session-a", content: "继续",
      continuation: { turnId: "turn-a", headId: "head-a", ledgerSeq: 12, agentId: "agent-a" },
      composerAttachments: [], references: [], queuedBehindActiveTurn: false });
    await act(async () => { finish({ turnId: "continued-turn" }); });
    await view.click(); expect(mutateAsync).toHaveBeenCalledOnce();
  });
  it("reuses the submission identity after an uncertain transport failure", async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error("network timeout"));
    const view = await mount(mutateAsync);
    await view.click(); await view.click();
    expect(mutateAsync).toHaveBeenCalledTimes(2);
    expect(mutateAsync.mock.calls[0][0].clientSubmissionId).toBe(mutateAsync.mock.calls[1][0].clientSubmissionId);
  });
  it("keeps the selected next-turn model when continuing", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    const modelSelection = { modelId: "provider/model", reasoningEffort: "high" };
    const view = await mount(mutateAsync, { modelSelection });
    await view.click();
    expect(mutateAsync.mock.calls[0][0].modelSelection).toEqual(modelSelection);
  });
  it("does not turn a stale rendered Play into a continuation of a newer turn", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    const view = await mount(mutateAsync);
    view.client.setQueryData(queryKeys.session("session-a"), { ...detail, ledgerSeq: 14 });
    await view.click(); expect(mutateAsync).not.toHaveBeenCalled();
  });
  it.each([{ activeDraftEffective: "new draft" }, { hasAttachments: true }, { hasReferences: true },
    { blocked: true }, { isModelParametersSavePending: () => true }])("preserves normal composer state %j", async (overrides) => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    const view = await mount(mutateAsync, overrides);
    await view.click(); expect(mutateAsync).not.toHaveBeenCalled();
  });
});
