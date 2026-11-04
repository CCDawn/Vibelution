// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LauncherAssistantEmbeddedRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: () => createElement("div", { "data-testid": "native-conversation" }),
}));

const STATUS = {
  assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
  operatorAssetsVersion: 1,
  settings: { ok: true, displayName: "助理", modelId: "model-1",
    preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的，随时吩咐。" } },
};
const QUEUED_ROW = { id: "q-1", position: 1, status: "queued", content: "排队消息" };
const HOLD = { reason: "user_stop", turnId: "turn-1", heldAt: "2026-11-04T00:00:00Z" };

let root: Root | undefined;
let container: HTMLDivElement;
let invoke: ReturnType<typeof vi.fn>;
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  container?.remove();
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

describe("launcher assistant queue hold hint", () => {
  it("says the queue is paused and how to resume while a stop hold freezes it", async () => {
    await renderEmbedded({
      id: "s", agentId: "a", status: "ready", messages: [],
      queuedTurns: [QUEUED_ROW],
      queueHold: HOLD,
    });
    const hint = container.querySelector<HTMLElement>("[data-launcher-assistant-queue-hold]");
    expect(hint).not.toBeNull();
    expect(hint?.textContent).toContain("队列已暂停");
    expect(hint?.textContent).toContain("发送新消息即可恢复");
    const section = container.querySelector<HTMLElement>("[data-launcher-assistant-queue]");
    expect(section?.textContent).toContain("已排队");
  });

  it("keeps the queue section silent about holds when no hold marker exists", async () => {
    await renderEmbedded({
      id: "s", agentId: "a", status: "ready", messages: [],
      queuedTurns: [QUEUED_ROW],
    });
    expect(container.querySelector("[data-launcher-assistant-queue-hold]")).toBeNull();
    expect(container.querySelector("[data-launcher-assistant-queue]")).not.toBeNull();
  });
});
