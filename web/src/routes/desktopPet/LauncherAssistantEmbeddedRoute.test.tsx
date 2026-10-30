// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantEmbeddedRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
// Retain the real embedded route and transport validators; replace only the
// expensive transcript renderer with its public composer contract.
let conversation: ConversationViewProps | undefined;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    return createElement("div", { "data-testid": "native-conversation" });
  },
}));

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
async function renderEmbedded() {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  invoke = vi.fn(async request => {
    switch (request.operation) {
      case "status": return {
        assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
        operatorAssetsVersion: 1,
        settings: { ok: true, displayName: "助理", modelId: "model-1",
          preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的，随时吩咐。" } },
      };
      case "config": return { language: "zh" };
      case "detail": return { id: "s", agentId: "a", status: "ready", messages: [] };
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

describe("Launcher embedded assistant page", () => {
  it("renders the full-size session page without floating-window chrome", async () => {
    await renderEmbedded();
    const page = container.querySelector<HTMLElement>('[data-assistant-embedded="true"]');
    expect(page).toBeTruthy();
    expect(page!.querySelector("h1")?.textContent).toBe("个人助理");
    expect(page!.querySelector('[role="status"]')?.textContent).toBe("在的，随时吩咐。");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
    expect(conversation?.composerActionMode).toBe("send");
    expect(conversation?.showHeader).toBe(false);
    const labels = [...container.querySelectorAll("button")]
      .map(button => button.textContent || button.getAttribute("aria-label"));
    expect(labels.some(label => label?.includes("电脑操作"))).toBe(true);
    expect(labels.some(label => label?.includes("打开 Launcher"))).toBe(false);
    expect(labels).not.toContain("展开个人助理聊天");
    expect(labels).not.toContain("收起聊天");
    expect(labels).not.toContain("隐藏个人助理");
    // The embedded page never resizes or hides a host window.
    expect(invoke.mock.calls.some(([request]) => request.operation === "setExpanded" || request.operation === "hide")).toBe(false);
    expect(container.querySelector('[data-expanded="false"]')).toBeNull();
    // The transparent pet root stays exclusive to the floating window.
    expect(document.documentElement.dataset.vibelutionDesktopPet).toBeUndefined();
    expect(document.body.dataset.vibelutionDesktopPet).toBeUndefined();
  });

  it("keeps the reading column capped by the embedded stylesheet contract", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const launcherCss = readFileSync(resolve(import.meta.dirname, "../../design/route-css/desktop-pet.tailwind.css"), "utf8");
    const block = launcherCss.match(/\[data-assistant-embedded="true"\] \.desktop-assistant-chat-body \{([^}]+)\}/)?.[1] || "";
    expect(block).toContain("max-width: 920px");
    expect(block).toContain("margin-inline: auto");
    await renderEmbedded();
    const body = container.querySelector<HTMLElement>(".desktop-assistant-chat-body");
    expect(body).toBeTruthy();
  });
});
