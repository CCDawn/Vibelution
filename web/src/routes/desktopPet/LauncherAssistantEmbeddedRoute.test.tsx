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
    // Honor the composer-preceding slot contract so route-owned panels land
    // in the DOM the same place the real composer surface would put them.
    return createElement("div", { "data-testid": "native-conversation" },
      props.composerPrecedingContent ?? null);
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
async function renderEmbedded(options: { dispatches?: Array<Record<string, unknown>> } = {}) {
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
      case "dispatches": return { dispatches: options.dispatches ?? [] };
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
    // Standard chat density: the embedded page leaves the 400px floating
    // window's compact presentation behind.
    expect(page!.dataset.assistantChat).toBe("embedded");
    expect(page!.querySelector("h1")?.textContent).toBe("个人助理");
    expect(page!.querySelector('[role="status"]')?.textContent).toBe("在的，随时吩咐。");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(conversation?.composerPlaceholder).toBe("和个人助理聊一聊…");
    expect(conversation?.composerActionMode).toBe("send");
    expect(conversation?.showHeader).toBe(false);
    const labels = [...container.querySelectorAll("button")]
      .map(button => button.textContent || button.getAttribute("aria-label"));
    expect(labels.some(label => label?.includes("电脑操作"))).toBe(true);
    // Without dispatches the receipts toggle stays hidden.
    expect(labels.some(label => label?.includes("任务回执"))).toBe(false);
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
    // The embedded density block keeps the structural fill rules only; the
    // compact size rules (fonts, paddings) stay scoped to "compact".
    const structural = launcherCss.match(/\[data-assistant-chat="embedded"\] [^\n]+\.layout \{([^}]+)\}/)?.[1] || "";
    expect(structural).toContain("flex: 1");
    expect(structural).toContain("height: 100%");
    await renderEmbedded();
    const body = container.querySelector<HTMLElement>(".desktop-assistant-chat-body");
    expect(body).toBeTruthy();
  });

  it("keeps dispatch receipts collapsed until the header toggle opens them", async () => {
    await renderEmbedded({ dispatches: [{
      dispatchId: "dispatch-1", projectId: "ccdawn-vibelution:main:0d6e4079e367:d9ccbfb82c3ec3",
      agentId: "worker", nativeTaskId: "task-1",
      receipt: { taskId: "task-1", status: "succeeded", resultSummary: "周报已生成", shouldPoll: false },
    }] });
    const toggle = [...container.querySelectorAll("button")].find(button => button.textContent === "任务回执 1");
    expect(toggle).toBeTruthy();
    // Folded by default: no receipt rows are visible anywhere on the page.
    expect(container.querySelector("[data-launcher-assistant-receipts]")).toBeNull();
    expect(container.textContent).not.toContain("成功");
    expect(container.textContent).not.toContain("周报已生成");
    expect(container.textContent).not.toContain("ccdawn-vibelution");
    await act(async () => toggle?.click()); await settle();
    const panel = container.querySelector<HTMLElement>("[data-launcher-assistant-receipts]");
    expect(panel).toBeTruthy();
    expect(panel!.textContent).toContain("成功");
    expect(panel!.textContent).toContain("周报已生成");
    // Humanized rows keep the raw project ID out of the visible text; only the
    // title attribute may carry the full value.
    const visible = panel!.cloneNode(true) as HTMLElement;
    visible.querySelectorAll("[title]").forEach(element => element.removeAttribute("title"));
    expect(visible.textContent).not.toContain("ccdawn-vibelution");
    expect(panel!.querySelector("[title]")?.getAttribute("title")).toBe("ccdawn-vibelution:main:0d6e4079e367:d9ccbfb82c3ec3");
    await act(async () => toggle?.click()); await settle();
    expect(container.querySelector("[data-launcher-assistant-receipts]")).toBeNull();
  });
});
