// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantEmbeddedRoute, LauncherAssistantRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => createElement("div", { "data-testid": "pet-character" }) }));
// Keep the real route and transport validators; only the transcript renderer is
// replaced with its public composer contract.
let conversation: ConversationViewProps | undefined;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    return createElement("div", { "data-testid": "native-conversation" });
  },
}));

const STATUS = {
  assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
  operatorAssetsVersion: 1,
  settings: { ok: true, displayName: "助理", modelId: "model-1",
    preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的，随时吩咐。" } },
};
const DETAIL = { id: "s", agentId: "a", status: "ready", messages: [] };

let root: Root | undefined;
let container: HTMLDivElement;
let invoke: ReturnType<typeof vi.fn>;
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  container?.remove(); conversation = undefined;
  vi.unstubAllGlobals(); vi.clearAllMocks(); vi.useRealTimers();
});
async function settle() {
  await act(async () => {
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(20);
    else await new Promise(resolve => setTimeout(resolve, 20));
  });
}
async function renderRoute(options: {
  embedded?: boolean;
  status?: () => Promise<unknown>;
} = {}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return options.status ? options.status() : STATUS;
      case "config": return { language: "zh" };
      case "detail": return DETAIL;
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "operatorAsset": return { schemaVersion: 1, kind: request.kind, image: null, readability: "standard" };
      default: throw new Error("unexpected_operation");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  const page = options.embedded === false
    ? createElement(LauncherAssistantRoute)
    : createElement(LauncherAssistantEmbeddedRoute);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, page)));
  await settle(); await settle();
}
function statusCalls() {
  return invoke.mock.calls.filter(([request]) => request.operation === "status").length;
}

describe("Launcher assistant backend wait", () => {
  it("renders the backend wait skeleton while the first status read fails", async () => {
    await renderRoute({ status: async () => { throw new Error("backend unreachable"); } });
    const waiting = container.querySelector('[data-launcher-assistant-waiting="backend"]');
    expect(waiting).toBeTruthy();
    expect(waiting?.getAttribute("data-tone")).toBe("loading");
    expect(waiting?.getAttribute("aria-busy")).toBe("true");
    expect(waiting?.textContent).toContain("正在等待工作台后端启动");
    // The underlying transport failure stays visible for diagnosability.
    expect(waiting?.textContent).toContain("backend unreachable");
    // Pulse skeleton lines are the light activity indicator.
    expect(waiting?.querySelectorAll('[aria-hidden="true"] .animate-pulse').length).toBeGreaterThan(0);
    // The conversation never mounts from a failed transport.
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeNull();
  });

  it("transitions to the normal assistant page once the backend answers", async () => {
    let statusFails = true;
    await renderRoute({ status: async () => { if (statusFails) throw new Error("backend unreachable"); return STATUS; } });
    expect(container.querySelector('[data-launcher-assistant-waiting="backend"]')).toBeTruthy();
    // The backend starts: a visibility flip refetches status, which now succeeds.
    statusFails = false;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    expect(container.querySelector('[data-launcher-assistant-waiting="backend"]')).toBeNull();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
  });

  it("keeps the collapsed float's waiting pill visible and recovers without a refresh", async () => {
    let statusFails = true;
    await renderRoute({ embedded: false, status: async () => { if (statusFails) throw new Error("backend unreachable"); return STATUS; } });
    const petRoot = container.querySelector('[data-vui-domain-recipe="launcher-assistant"][data-expanded="false"]');
    expect(petRoot?.getAttribute("data-waiting")).toBe("backend");
    expect(petRoot?.textContent).toContain("正在等待工作台后端启动");
    expect(container.querySelector('[data-testid="pet-character"]')).toBeTruthy();
    // The backend starts: the same float returns to its normal status line.
    statusFails = false;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle(); await settle();
    expect(petRoot?.getAttribute("data-waiting")).toBeNull();
    expect(petRoot?.textContent).not.toContain("正在等待工作台后端启动");
    // The recovered float shows the normal idle status line again.
    expect(petRoot?.textContent).toContain("在的，随时吩咐。");
  });

  it("auto-probes the unreachable backend with a growing backoff cadence", async () => {
    vi.useFakeTimers();
    await renderRoute({ status: async () => { throw new Error("backend unreachable"); } });
    const afterMount = statusCalls();
    // First wait window: one follow-up probe within ~2s.
    await act(async () => { await vi.advanceTimersByTimeAsync(2_100); });
    expect(statusCalls()).toBe(afterMount + 1);
    // Second probe still lands inside the first 4s wait window.
    const afterFirstRetry = statusCalls();
    await act(async () => { await vi.advanceTimersByTimeAsync(2_100); });
    expect(statusCalls()).toBe(afterFirstRetry + 1);
    // The cadence has now doubled: a further 2.1s slice stays silent.
    const afterSecondRetry = statusCalls();
    await act(async () => { await vi.advanceTimersByTimeAsync(2_100); });
    expect(statusCalls()).toBe(afterSecondRetry);
  });
});
