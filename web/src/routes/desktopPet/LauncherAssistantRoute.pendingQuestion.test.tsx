// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantEmbeddedRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
// Only the transcript renderer is replaced with its public composer contract.
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
function detailWith(options: { status?: string; lastTurnTerminalTurnId?: string; pendingQuestion?: Record<string, string> | null } = {}) {
  return {
    id: "s", agentId: "a", status: options.status ?? "ready",
    messages: [],
    lastTurnTerminalTurnId: options.lastTurnTerminalTurnId ?? "turn-9",
    pendingQuestion: options.pendingQuestion === undefined
      ? { id: "q-1", questionText: "要继续部署吗？", askedAt: "2026-05-22T10:00:00Z", turnId: "turn-9" }
      : options.pendingQuestion,
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
async function renderEmbedded(detail: Record<string, unknown>) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return STATUS;
      case "config": return { language: "zh" };
      case "detail": return detail;
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "operatorAsset": return { schemaVersion: 1, kind: request.kind, image: null, readability: "standard" };
      default: throw new Error("unexpected_operation");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantEmbeddedRoute))));
  await settle(); await settle();
}

describe("Launcher assistant pending question banner", () => {
  it("renders the compact info banner above the composer for a fresh question", async () => {
    await renderEmbedded(detailWith());
    const banner = container.querySelector('section[data-vui="state-surface"][data-density="compact"][data-tone="info"]');
    expect(banner?.getAttribute("data-launcher-assistant-pending-question")).toBe("q-1");
    expect(banner?.textContent).toContain("待你回答");
    expect(banner?.textContent).toContain("要继续部署吗？");
  });

  it("hides the banner while the session owns execution", async () => {
    await renderEmbedded(detailWith({ status: "running" }));
    expect(container.querySelector('[data-vui="state-surface"][data-tone="info"]')).toBeNull();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
  });

  it("hides the banner when the question belongs to an earlier turn than the terminal tail", async () => {
    await renderEmbedded(detailWith({
      pendingQuestion: { id: "q-old", questionText: "旧问题", askedAt: "2026-05-22T09:00:00Z", turnId: "turn-old" },
    }));
    expect(container.querySelector('[data-vui="state-surface"][data-tone="info"]')).toBeNull();
  });

  it("renders nothing when the slot is empty", async () => {
    await renderEmbedded(detailWith({ pendingQuestion: null }));
    expect(container.querySelector('[data-vui="state-surface"][data-tone="info"]')).toBeNull();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
  });
});
