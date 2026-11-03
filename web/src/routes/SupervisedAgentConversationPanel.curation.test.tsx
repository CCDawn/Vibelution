/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import { resetControlTokenForTests, seedControlTokenForTests } from "../api/client";
import type { ConversationMessage } from "../api/types";
import { prefetchConversationView } from "../components/conversation/LazyConversationView";
import { VuiProvider } from "../components/vui/VuiProvider";
import { dictionary } from "../i18n/dictionary";
import { SupervisedAgentConversationPanel } from "./SupervisedAgentConversationPanel";

const fetchSessionDetailWindow = vi.hoisted(() => vi.fn());
vi.mock("./chat/chatSessionDetailHelpers", () => ({ fetchSessionDetailWindow }));

const evidence: ConversationMessage = {
  id: "audit-assistant", role: "assistant", timestamp: "2026-11-03T00:00:00Z",
  turnId: "audit-turn", status: "completed",
  turnItems: [{
    id: "audit-answer:1", itemId: "audit-answer", version: 3,
    sessionId: "simulation-baseline-audit", turnId: "audit-turn", status: "completed",
    revision: 1, sequence: 1, type: "agent_message", phase: "final_answer",
    text: "AUDIT: synthetic recorded evidence", terminal: true,
  }],
};
const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
const previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
let host: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;
let network: ReturnType<typeof vi.fn>;

async function renderEvidence(sessionId: string, executionMode: string) {
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <VuiProvider>
            <SupervisedAgentConversationPanel
              compact
              members={[{
                role: "baseline", label: "Baseline", name: "AUDIT", model: "", modelId: "", agentId: "",
                status: "configured", executionMode,
                conversationSession: { role: "baseline", status: "completed", conversationSessionId: sessionId },
                chatRoute: "", configRoute: "",
              }]}
              selectedRole="baseline"
              fallbackMessages={[evidence]}
              taskSummary="AUDIT synthetic summary"
              isLive={false}
              runStatus="done"
              lang="zh"
              roleLabel={(role) => role || ""}
              roleDescription={(role) => role}
              statusLabel={(status) => status}
              onSelectRole={() => undefined}
              onFollowLive={() => undefined}
            />
          </VuiProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
  for (let attempt = 0; attempt < 80; attempt += 1) {
    await act(async () => { await new Promise<void>((resolve) => window.setTimeout(resolve, 25)); });
    if (host.textContent?.includes("AUDIT: synthetic recorded evidence")) break;
  }
  expect(host.querySelector("[data-conversation-following]")).not.toBeNull();
}

describe("supervised embedded evidence with the real ConversationView", () => {
  beforeEach(async () => {
    actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    seedControlTokenForTests();
    // Match the existing ConversationView.visibleMessages fixture: happy-dom
    // has no layout, while settled transcript rows use the measured viewport.
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 1280, height: 900, top: 0, left: 0, right: 1280, bottom: 900, x: 0, y: 0, toJSON: () => ({}) });
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1280);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(900);
    network = vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", network);
    await prefetchConversationView();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh", modelLabels: {} });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
    fetchSessionDetailWindow.mockReset().mockImplementation(async (sessionId: string) => ({ id: sessionId, messages: [evidence], status: "completed" }));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    queryClient.clear();
    resetControlTokenForTests();
    host.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  });

  it("renders simulation evidence without any native Session API request", async () => {
    await renderEvidence("simulation-baseline-audit", "simulation");

    expect(host.textContent).toContain("AUDIT: synthetic recorded evidence");
    expect(host.querySelector('button[aria-label="复制回答"]')).not.toBeNull();
    expect(host.querySelector('button[aria-label="加入数据集"]')).toBeNull();
    expect(host.querySelector('button[aria-label="排除"]')).toBeNull();
    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    expect(network.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("/api/sessions/"))).toEqual([]);
  });

  it("preserves native message-curation requests for a real Session", async () => {
    await renderEvidence("native-session", "real");

    expect(host.textContent).toContain("AUDIT: synthetic recorded evidence");
    expect(fetchSessionDetailWindow).toHaveBeenCalled();
    expect(host.querySelector('button[aria-label="加入数据集"]')).not.toBeNull();
    expect(host.querySelector('button[aria-label="排除"]')).not.toBeNull();
    expect(network.mock.calls.map(([url]) => String(url))).toContain("/api/sessions/native-session/curation");
    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label="加入数据集"]')!.click();
      await Promise.resolve();
    });
    expect(network).toHaveBeenCalledWith(
      "/api/sessions/native-session/messages/audit-assistant/curation",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "include" }) }),
    );
  });
});
