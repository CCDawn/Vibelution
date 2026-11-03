/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import type { ConversationMessage, SessionDetail } from "../api/types";
import { VuiProvider } from "../components/vui/VuiProvider";
import { SupervisedAgentConversationPanel, type SupervisedAgentConversationPanelProps } from "./SupervisedAgentConversationPanel";
import type { SupervisedRunMember } from "./evolution/evolutionRouteModel";

const fetchSessionDetailWindow = vi.hoisted(() => vi.fn());
vi.mock("./chat/chatSessionDetailHelpers", () => ({ fetchSessionDetailWindow }));
vi.mock("../components/conversation/LazyConversationView", () => ({
  LazyConversationView: ({ messages, sessionId }: { messages: ConversationMessage[]; sessionId: string }) => (
    <div data-testid="conversation" data-session-id={sessionId}>{messages.map((message) => (
      message.role === "user" ? message.content : message.turnItems.map((item) => "text" in item ? item.text : "").join("\n")
    )).join("\n")}</div>
  ),
}));

function member(sessionId: string, executionMode?: string): SupervisedRunMember {
  return {
    role: "baseline",
    label: "Baseline",
    name: "Baseline Agent",
    model: "Test model",
    modelId: "test-model",
    agentId: "baseline-agent",
    status: "configured",
    conversationSession: { role: "baseline", status: "completed", conversationSessionId: sessionId },
    chatRoute: `/chat?session=${sessionId}`,
    configRoute: "",
    executionMode,
  };
}

function message(content: string): ConversationMessage {
  return {
    id: content, role: "assistant", timestamp: "2026-11-03T00:00:00Z",
    turnId: "audit-turn", status: "completed",
    turnItems: [{
      id: "audit-answer:1", itemId: "audit-answer", version: 3,
      sessionId: "audit-evidence", turnId: "audit-turn", status: "completed",
      revision: 1, sequence: 1, type: "agent_message", phase: "final_answer", text: content,
    }],
  };
}

function detail(sessionId: string, content: string): SessionDetail {
  return { id: sessionId, messages: [message(content)], status: "completed" } as SessionDetail;
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

let host: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;
let onFollowLive: ReturnType<typeof vi.fn>;
const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
const previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;

async function settleQuery() {
  await act(async () => { await new Promise<void>((resolve) => window.setTimeout(resolve, 0)); });
}

async function renderPanel(selected: SupervisedRunMember, patch: Partial<SupervisedAgentConversationPanelProps> = {}) {
  const props: SupervisedAgentConversationPanelProps = {
    members: [selected],
    selectedRole: "baseline",
    fallbackMessages: [],
    taskSummary: "Synthetic evaluation summary",
    isLive: false,
    runStatus: "done",
    lang: "zh",
    roleLabel: (role) => role || "",
    roleDescription: (role) => role,
    statusLabel: (status) => status,
    onSelectRole: vi.fn(),
    onFollowLive,
    ...patch,
  };
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/supervised-evolution"]}>
          <VuiProvider>
            <SupervisedAgentConversationPanel {...props} />
            <LocationProbe />
          </VuiProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await Promise.resolve();
  });
}

describe("SupervisedAgentConversationPanel session ownership", () => {
  beforeEach(() => {
    actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    onFollowLive = vi.fn();
    fetchSessionDetailWindow.mockReset().mockImplementation(async (sessionId: string) => detail(sessionId, "Native session output"));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    queryClient.clear();
    host.remove();
    vi.useRealTimers();
    actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  });

  it.each([
    ["simulation-baseline-run", undefined],
    ["simulation-judge-legacy-run", "real"],
    ["opaque-simulation-evidence", "simulation"],
  ])("keeps simulation %s out of native queries, cache and navigation", async (sessionId, executionMode) => {
    queryClient.setQueryData(queryKeys.session(sessionId!), detail(sessionId!, "Cached native session output"));

    await renderPanel(member(sessionId!, executionMode));

    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain("Cached native session output");
    expect(host.textContent).not.toContain("完整会话");
    expect(host.textContent).toContain("模拟运行证据");
    expect(host.textContent).toContain("Synthetic evaluation summary");
  });

  it("shows recorded simulation messages without fetching a native session", async () => {
    await renderPanel(member("simulation-baseline-run"), { fallbackMessages: [message("Recorded simulation evidence")] });

    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    expect(host.textContent).toContain("Recorded simulation evidence");
    expect(host.textContent).not.toContain("完整会话");
    expect(host.querySelector('[data-testid="conversation"]')?.getAttribute("data-session-id")).toBe("");
  });

  it("shows the simulation summary in the compact evolution workspace", async () => {
    await renderPanel(member("opaque-evidence", "simulation"), { compact: true });

    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    expect(host.textContent).toContain("模拟运行证据");
    expect(host.textContent).toContain("Synthetic evaluation summary");
    expect(host.textContent).not.toContain("完整会话");
  });

  it.each(["real", undefined])("fetches and opens a real session with mode %s", async (executionMode) => {
    await renderPanel(member("native-session", executionMode));
    await settleQuery();
    await vi.waitFor(() => expect(host.textContent).toContain("Native session output"));

    expect(fetchSessionDetailWindow).toHaveBeenCalledWith("native-session", expect.objectContaining({ messageLimit: 80 }));
    expect(host.querySelector('[data-testid="conversation"]')?.getAttribute("data-session-id")).toBe("native-session");
    const action = [...host.querySelectorAll("button")].find((button) => button.textContent?.includes("完整会话"));
    expect(action).toBeDefined();
    await act(async () => action!.click());
    expect(host.querySelector('[data-testid="location"]')?.textContent).toBe("/chat?session=native-session");
  });

  it("keeps a missing real session error visible", async () => {
    fetchSessionDetailWindow.mockRejectedValue(new Error("404 Session not found"));
    await renderPanel(member("missing-native-session", "real"));
    await settleQuery();
    await vi.waitFor(() => expect(host.textContent).toContain("404 Session not found"));

    expect(fetchSessionDetailWindow).toHaveBeenCalled();
    expect(host.textContent).toContain("完整会话暂时无法刷新");
    expect(host.textContent).not.toContain("模拟运行证据");
  });

  it("continues polling and following a live native conversation", async () => {
    vi.useFakeTimers();
    await renderPanel(member("native-session", "real"), { isLive: true, runStatus: "running", activeRole: "judge" });
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(2);

    const follow = [...host.querySelectorAll("button")].find((button) => button.textContent?.includes("跟随现场"));
    expect(follow).toBeDefined();
    await act(async () => follow!.click());
    expect(onFollowLive).toHaveBeenCalledTimes(1);
  });
});
