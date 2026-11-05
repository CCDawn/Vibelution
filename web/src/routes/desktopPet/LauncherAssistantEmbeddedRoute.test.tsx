// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantEmbeddedRoute, LauncherAssistantRoute } from "./LauncherAssistantRoute";

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
      props.composerPrecedingContent ?? null,
      createElement("div", { "data-testid": "composer-toolbar" }, props.composerLeadingControl, props.composerModelControl));
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
async function renderEmbedded(options: { dispatches?: Array<Record<string, unknown>>; navigationOwned?: boolean } = {}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  let selectedModel = "model-1";
  invoke = vi.fn(async request => {
    switch (request.operation) {
      case "status": return {
        assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
        operatorAssetsVersion: 1,
        settings: { ok: true, displayName: "助理", modelId: selectedModel,
          modelChoices: ["model-1", "model-2"].map(modelId => ({ modelId, label: modelId === "model-1" ? "当前对话模型" : "备用对话模型",
            providerLabel: "官方", isDefault: modelId === "model-1", providerHealthy: true, missingApiKey: false, availability: "ready" })),
          preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的，随时吩咐。" } },
      };
      case "config": return { language: "zh" };
      case "setModel": selectedModel = request.modelId; return { modelId: selectedModel };
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
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, options.navigationOwned
    ? createElement(LauncherAssistantRoute, { embedded: true, navigationOwned: true })
    : createElement(LauncherAssistantEmbeddedRoute))));
  await settle(); await settle();
}

describe("Launcher embedded assistant page", () => {
  it("switches models through the original native bridge from the shared toolbar", async () => {
    await renderEmbedded();
    const httpCallsBefore = vi.mocked(fetch).mock.calls.length;
    const model = container.querySelector<HTMLButtonElement>('[data-launcher-assistant-model-control] button')!;
    await act(async () => model.click());
    const selectTrigger = document.querySelector<HTMLElement>('[role="combobox"][aria-label="切换助理模型"]')!;
    await act(async () => selectTrigger.click());
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(node => node.textContent === "备用对话模型")!;
    await act(async () => option.click());
    await settle();
    expect(invoke.mock.calls.filter(([request]) => request.operation === "setModel").map(([request]) => request))
      .toEqual([{ operation: "setModel", modelId: "model-2" }]);
    expect(container.querySelector('[data-launcher-assistant-model-control] button')?.textContent).toBe("备用对话模型");
    expect(vi.mocked(fetch).mock.calls).toHaveLength(httpCallsBefore);
  });
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
    expect(conversation?.composerVariant).toBe("codex");
    expect(conversation?.density).toBe("default");
    expect(container.querySelector('[data-launcher-assistant-model-row]')).toBeNull();
    expect(container.querySelector('[data-testid="composer-toolbar"] [data-launcher-assistant-model-control]')).toBeTruthy();
    expect(container.querySelector('[data-testid="composer-toolbar"] button[aria-label="更多操作"]')).toBeTruthy();
    expect(conversation?.showHeader).toBe(false);
    const labels = [...container.querySelectorAll("button")]
      .map(button => button.textContent || button.getAttribute("aria-label"));
    expect(labels.some(label => label?.includes("电脑操作"))).toBe(true);
    // Without dispatches the receipts toggle stays hidden.
    expect(labels.some(label => label?.includes("任务结果"))).toBe(false);
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

  it("leaves conversation geometry to the shared surface in both Launcher hosts", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const launcherCss = readFileSync(resolve(import.meta.dirname, "../../design/route-css/desktop-pet.tailwind.css"), "utf8");
    const block = launcherCss.match(/\[data-assistant-embedded="true"\] \.desktop-assistant-chat-body \{([^}]+)\}/)?.[1] || "";
    expect(block).toContain("width: 100%");
    expect(block).not.toContain("max-width:");
    expect(block).toContain("margin-inline: auto");
    // Hosts own outer structure; neither host overrides shared composer,
    // transcript, model controls or avatars with a second visual contract.
    expect(launcherCss).not.toMatch(/\[data-assistant-chat="(?:compact|embedded)"\][^{]*\.vui-components-conversationview/);
    expect(launcherCss).not.toContain('[data-testid="conversation-turn-model-control"]');
    expect(launcherCss).not.toContain('[data-operator-avatar="custom"]');
    const structural = launcherCss.match(/\[data-assistant-chat="embedded"\] [^\n]+\.layout \{([^}]+)\}/)?.[1] || "";
    expect(structural).toContain("flex: 1");
    expect(structural).toContain("height: 100%");
    await renderEmbedded();
    const body = container.querySelector<HTMLElement>(".desktop-assistant-chat-body");
    expect(body).toBeTruthy();
  });

  it.each([false, true])("leaves task status reporting to the Agent (navigationOwned=%s)", async navigationOwned => {
    await renderEmbedded({ navigationOwned, dispatches: [{
      dispatchId: "dispatch-1", projectId: "ccdawn-vibelution:main:0d6e4079e367:d9ccbfb82c3ec3",
      agentId: "worker", nativeTaskId: "task-1",
      receipt: { taskId: "task-1", status: "succeeded", resultSummary: "周报已生成", shouldPoll: false },
    }] });
    const toggle = [...container.querySelectorAll("button")].find(button => button.textContent === "任务结果 1");
    expect(toggle).toBeUndefined();
    expect(container.querySelector("[data-launcher-assistant-receipts]")).toBeNull();
    expect(container.textContent).not.toContain("成功");
    expect(container.textContent).not.toContain("周报已生成");
    expect(container.textContent).not.toContain("ccdawn-vibelution");
  });
  it("hides the task results button in unified navigation when there are no records", async () => {
    await renderEmbedded({ navigationOwned: true });
    expect([...container.querySelectorAll("button")].some(button => button.textContent?.includes("任务结果"))).toBe(false);
  });
});
