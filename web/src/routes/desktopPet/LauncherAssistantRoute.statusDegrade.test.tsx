// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantEmbeddedRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
// Keep the real route and transport validators; only the transcript renderer is
// replaced with its public composer contract.
let conversation: ConversationViewProps | undefined;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    return createElement("div", { "data-testid": "native-conversation" },
      props.composerPrecedingContent ?? null);
  },
}));

const STATUS = {
  assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
  operatorAssetsVersion: 1,
  settings: { ok: true, displayName: "助理", modelId: "model-1",
    preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的，随时吩咐。" } },
};
const DETAIL = { id: "s", agentId: "a", status: "ready", messages: [] };
const APPROVAL = {
  approvalId: "approval-1", toolName: "write_file", risk: "medium",
  targetSummary: { path: "report.md" }, revision: "rev-1",
  availableDecisions: ["accept", "decline"],
};
const REVISION = "a".repeat(64);
const PREVIEW = {
  taskId: "task-1", sessionId: "native-session", agentId: "worker", requestId: "approval-1",
  turnId: "turn-1", callId: "call-1", toolName: "write_file", revision: REVISION,
  approval: "ask", risk: "medium", permissionPreset: "default", decisionFingerprint: "fp-1",
  configRevision: 1, configHash: "hash-1",
  argumentsJson: '{"path":"report.md"}', executionArgumentsJson: '{"path":"report.md"}',
};
function dispatchWithApproval(index: string) {
  return {
    dispatchId: `dispatch-${index}`, projectId: "project-1", agentId: "worker", nativeTaskId: `task-${index}`,
    receipt: { taskId: `task-${index}`, status: "running", resultSummary: "", shouldPoll: false,
      pendingApprovals: [{ ...APPROVAL }] },
  };
}

let root: Root | undefined;
let container: HTMLDivElement;
let invoke: ReturnType<typeof vi.fn>;
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  container?.remove(); conversation = undefined;
  vi.unstubAllGlobals(); vi.clearAllMocks();
});
async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}
async function renderEmbedded(options: {
  status?: () => Promise<unknown>;
  dispatches?: Array<Record<string, unknown>>;
  onDecide?: (request: Record<string, unknown>) => Promise<unknown>;
} = {}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return options.status ? options.status() : STATUS;
      case "config": return { language: "zh" };
      case "detail": return DETAIL;
      case "approvals": return [];
      case "dispatches": return { dispatches: options.dispatches ?? [] };
      case "operatorAsset": return { schemaVersion: 1, kind: request.kind, image: null, readability: "standard" };
      case "previewDispatchApproval": return { ...PREVIEW };
      case "decideDispatchApproval": return options.onDecide
        ? options.onDecide(request)
        : { dispatchId: request.dispatchId, taskId: request.taskId, approvalId: request.approvalId, revision: request.revision, decision: request.decision };
      default: throw new Error("unexpected_operation");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantEmbeddedRoute))));
  await settle(); await settle();
}
function button(text: string) {
  return [...container.querySelectorAll("button")].find(candidate => candidate.textContent?.includes(text));
}

describe("Launcher assistant status degradation", () => {
  it("keeps transcript and composer mounted behind a recovery banner when status fails after load", async () => {
    let statusFails = false;
    await renderEmbedded({ status: async () => { if (statusFails) throw new Error("host restarting"); return STATUS; } });
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
    // A visibility flip refetches status, which now fails (host restarting).
    statusFails = true;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    // The session page is not replaced by a full-page error surface.
    expect(container.querySelector('[data-assistant-embedded="true"]')).toBeTruthy();
    expect(container.querySelector('[data-vui="state-surface"][data-fill="true"]')).toBeNull();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
    // One compact banner explains the degraded status and offers a retry.
    const banner = container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="error"]');
    expect(banner?.textContent).toContain("个人助理状态轮询暂不可用");
    expect(banner?.textContent).toContain("host restarting");
    const retry = banner && [...banner.querySelectorAll("button")].find(candidate => candidate.textContent === "重试");
    expect(retry).toBeTruthy();
    // Retrying once status recovers removes the banner again.
    statusFails = false;
    await act(async () => retry!.click());
    await settle();
    expect(container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="error"]')).toBeNull();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
  });

  it("waits for the backend on a first-load failure with no session content", async () => {
    await renderEmbedded({ status: async () => { throw new Error("host restarting"); } });
    // No session data has ever loaded: the cold-boot wait skeleton stays
    // (the transport keeps probing, so a late backend is joined automatically).
    const surface = container.querySelector('[data-vui="state-surface"][data-fill="true"][data-tone="loading"]');
    expect(surface?.textContent).toContain("正在等待工作台后端启动");
    expect(surface?.textContent).toContain("host restarting");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeNull();
    expect(container.querySelector('[data-assistant-embedded="true"]')).toBeNull();
  });
});

describe("Launcher dispatch approval unlock", () => {
  it("releases the dialog buttons after a failed decision so the rejection can be retried", async () => {
    let decideAttempts = 0;
    await renderEmbedded({ dispatches: [dispatchWithApproval("1")],
      onDecide: async () => {
        decideAttempts += 1;
        if (decideAttempts === 1) throw new Error("host busy");
        return { dispatchId: "dispatch-1", taskId: "task-1", approvalId: "approval-1", revision: REVISION, decision: "decline" };
      } });
    const dialog = container.querySelector('[data-chat-tool-approval-variant="composer"]');
    expect(dialog).toBeTruthy();
    const reject = [...container.querySelectorAll("button")].find(candidate => candidate.textContent?.includes("拒绝"));
    expect(reject?.hasAttribute("disabled")).toBe(false);
    // First rejection fails; the error card explains it while the dialog unlocks.
    await act(async () => reject!.click());
    await settle(); await settle();
    expect(container.textContent).toContain("审批结果未确认");
    const retryReject = [...container.querySelectorAll("button")].find(candidate => candidate.textContent?.includes("拒绝"));
    expect(retryReject?.hasAttribute("disabled")).toBe(false);
    // The second click reaches the transport again instead of staying locked.
    await act(async () => retryReject!.click());
    await settle(); await settle();
    const decideCalls = invoke.mock.calls.filter(([request]) => request.operation === "decideDispatchApproval");
    expect(decideCalls.length).toBe(2);
  });
});

describe("Launcher dispatch receipt cap", () => {
  it("caps the receipt scan at 50 rows so history beyond the cap cannot surface approvals", async () => {
    const rows = Array.from({ length: 50 }, (_, index) => ({ dispatchId: `dispatch-old-${index}` }));
    rows.push(dispatchWithApproval("99"));
    await renderEmbedded({ dispatches: rows });
    expect(container.querySelector("[data-launcher-assistant-approval-dock]")).toBeNull();
    expect(container.querySelector('[data-chat-tool-approval-variant="composer"]')).toBeNull();
    expect(invoke.mock.calls.some(([request]) => request.operation === "previewDispatchApproval")).toBe(false);
  });

  it("still surfaces a pending approval that sits inside the 50-row cap", async () => {
    const rows = Array.from({ length: 49 }, (_, index) => ({ dispatchId: `dispatch-old-${index}` }));
    rows.unshift(dispatchWithApproval("1"));
    await renderEmbedded({ dispatches: rows });
    expect(container.querySelector("[data-launcher-assistant-approval-dock]")).toBeTruthy();
    expect(invoke.mock.calls.some(([request]) => request.operation === "previewDispatchApproval")).toBe(true);
  });
});
