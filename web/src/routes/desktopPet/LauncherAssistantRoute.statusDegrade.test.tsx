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
  detail?: () => Promise<unknown>;
  dispatches?: Array<Record<string, unknown>>;
  onDecide?: (request: Record<string, unknown>) => Promise<unknown>;
  onSessionEvent?: (listener: (value: unknown) => void) => (() => void) | void;
} = {}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return options.status ? options.status() : STATUS;
      case "config": return { language: "zh" };
      case "detail": return options.detail ? options.detail() : DETAIL;
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
  vi.stubGlobal("vibelutionLauncherAssistant", {
    invoke,
    ...(options.onSessionEvent
      ? { onSessionEvent: (listener: (value: unknown) => void) => options.onSessionEvent?.(listener) }
      : {}),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantEmbeddedRoute))));
  await settle(); await settle();
}
function button(text: string) {
  return [...container.querySelectorAll("button")].find(candidate => candidate.textContent?.includes(text));
}

describe("Launcher assistant status degradation", () => {
  it("keeps transcript and composer mounted behind a weak hint on a single failed status poll", async () => {
    let statusFails = false;
    await renderEmbedded({ status: async () => { if (statusFails) throw new Error("host restarting"); return STATUS; } });
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
    // A visibility flip refetches status, which now fails once (host restarting).
    statusFails = true;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    // The session page is not replaced by a full-page error surface and the
    // conversation stays mounted.
    expect(container.querySelector('[data-assistant-embedded="true"]')).toBeTruthy();
    expect(container.querySelector('[data-vui="state-surface"][data-fill="true"]')).toBeNull();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
    // One failed poll never raises a red banner; it stays a compact non-error hint.
    expect(container.querySelector('[data-vui="state-surface"][data-tone="error"]')).toBeNull();
    const hint = container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="unavailable"]');
    expect(hint?.textContent).toContain("状态刷新延迟");
    // The header keeps the normal session status line for a weak degradation.
    expect(container.textContent).toContain("在的，随时吩咐。");
    expect(container.textContent).not.toContain("个人助理暂不可用");
  });

  it("raises the red banner after a second consecutive failure over a dead push channel, and recovers", async () => {
    let statusFails = false;
    await renderEmbedded({ status: async () => { if (statusFails) throw new Error("host restarting"); return STATUS; } });
    // No onSessionEvent bridge was stubbed: the push channel never spoke, so it
    // counts as dead. First failure stays at the weak hint.
    statusFails = true;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    expect(container.querySelector('[data-vui="state-surface"][data-tone="error"]')).toBeNull();
    // Second consecutive failure: one compact red banner explains the degraded
    // status and offers a retry.
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    const banner = container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="error"]');
    expect(banner?.textContent).toContain("个人助理状态轮询暂不可用");
    expect(banner?.textContent).toContain("host restarting");
    const retry = banner && [...banner.querySelectorAll("button")].find(candidate => candidate.textContent === "重试");
    expect(retry).toBeTruthy();
    // The header reports unavailable too, while the conversation stays mounted.
    expect(container.textContent).toContain("个人助理暂不可用");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
    // Retrying once status recovers clears the whole degradation again.
    statusFails = false;
    await act(async () => retry!.click());
    await settle(); await settle();
    expect(container.querySelector('[data-vui="state-surface"][data-tone="error"]')).toBeNull();
    expect(container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="unavailable"]')).toBeNull();
    expect(container.textContent).not.toContain("个人助理暂不可用");
    expect(container.textContent).toContain("在的，随时吩咐。");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
  });

  it("keeps the weak hint while push events prove the conversation is still live", async () => {
    let statusFails = false;
    let emitEvent: ((value: unknown) => void) | undefined;
    await renderEmbedded({
      status: async () => { if (statusFails) throw new Error("host restarting"); return STATUS; },
      onSessionEvent: listener => { emitEvent = value => listener(value); },
    });
    // A heartbeat inside the health window proves the push channel alive.
    await act(async () => emitEvent?.({ type: "heartbeat", sessionId: "s", at: Date.now() }));
    statusFails = true;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    // Two consecutive failures with a live push channel never escalate: the
    // session content is still updating, so only the weak hint shows.
    expect(container.querySelector('[data-vui="state-surface"][data-tone="error"]')).toBeNull();
    expect(container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="unavailable"]')?.textContent).toContain("状态刷新延迟");
    expect(container.textContent).not.toContain("个人助理暂不可用");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
  });

  it("keeps one red story: the detail banner stands down while the status banner is red", async () => {
    let statusFails = false;
    let detailFails = false;
    await renderEmbedded({
      status: async () => { if (statusFails) throw new Error("host restarting"); return STATUS; },
      detail: async () => { if (detailFails) throw new Error("detail read failed"); return DETAIL; },
    });
    statusFails = true;
    detailFails = true;
    // First flip: status fails once (weak hint) while the detail read fails
    // outright — the detail failure is the only red, with its own retry.
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    expect(container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="error"]')).toBeNull();
    const detailBanner = container.querySelector('section[data-vui="state-surface"][data-tone="error"]');
    expect(detailBanner?.textContent).toContain("个人助理暂不可用");
    expect(detailBanner?.textContent).toContain("detail read failed");
    // Second flip: the status banner turns red and the detail banner stands
    // down, so the jitter shows exactly one red surface.
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    expect(container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="error"]')?.textContent).toContain("个人助理状态轮询暂不可用");
    expect(container.textContent).not.toContain("detail read failed");
    expect(container.querySelector('section[data-vui="state-surface"][data-tone="error"][data-density="default"]')).toBeNull();
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
