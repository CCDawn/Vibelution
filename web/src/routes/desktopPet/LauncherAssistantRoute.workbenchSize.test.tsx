// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";
import { LAUNCHER_ASSISTANT_WIDE_MIN_WIDTH } from "./launcherAssistantModel";

const launcherCss = readFileSync(resolve(import.meta.dirname, "../../design/route-css/desktop-pet.tailwind.css"), "utf8");

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
let conversation: ConversationViewProps | undefined;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    return createElement("div", { "data-testid": "native-conversation" });
  },
}));

let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let invoke: ReturnType<typeof vi.fn>;
const defaultInnerWidth = window.innerWidth;
beforeAll(() => vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true));
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  client?.clear(); container?.remove(); conversation = undefined;
  window.innerWidth = defaultInnerWidth;
  vi.clearAllMocks(); vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}

async function renderAssistant(options: { width: number; bridge?: boolean }) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  window.innerWidth = options.width;
  if (options.bridge !== false) {
    invoke = vi.fn(async (request: Record<string, unknown>) => {
      switch (request.operation) {
        case "status": return { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" } };
        case "config": return { language: "zh" };
        case "detail": return { id: "s", agentId: "a", status: "ready", messages: [] };
        case "approvals": return [];
        case "dispatches": return { dispatches: [] };
        case "setExpanded": return { expanded: request.expanded };
        case "openLauncher": return { opened: true };
        default: throw new Error("unexpected_operation");
      }
    });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  }
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => { root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantRoute))); });
  await settle(); await settle();
}

describe("LauncherAssistantRoute host-size tiers", () => {
  it("opens the expanded chat column directly at workbench size without a native resize", async () => {
    await renderAssistant({ width: 2543 });
    expect(container.querySelector('[data-expanded="true"]')).toBeTruthy();
    expect(container.querySelector('[data-assistant-chat="compact"]')).toBeTruthy();
    // The capped reading column wraps messages, composer, receipts and approvals.
    expect(container.querySelector(".desktop-assistant-chat-body")).toBeTruthy();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    // The collapsed pet stage never renders and no native resize is requested.
    expect(container.querySelector('[data-expanded="false"]')).toBeNull();
    expect(container.querySelector(".desktop-pet-stage")).toBeNull();
    expect(container.querySelector('button[aria-label="展开个人助理聊天"]')).toBeNull();
    expect(invoke.mock.calls.some(([request]) => request.operation === "setExpanded")).toBe(false);
  });

  it("keeps the native floating-window stage unchanged at compact size", async () => {
    await renderAssistant({ width: 400 });
    expect(container.querySelector('[data-expanded="false"]')).toBeTruthy();
    expect(container.querySelector(".desktop-pet-stage")).toBeTruthy();
    expect(container.querySelector(".desktop-assistant-chat-body")).toBeNull();
    const expand = container.querySelector<HTMLButtonElement>('button[aria-label="展开个人助理聊天"]');
    expect(expand).toBeTruthy();
    // The compact tier still expands through the same native resize handshake.
    await act(async () => { expand!.click(); });
    await settle(); await settle();
    expect(container.querySelector('[data-expanded="true"]')).toBeTruthy();
    expect(container.querySelector(".desktop-assistant-chat-body")).toBeTruthy();
    const resizeCalls = invoke.mock.calls.filter(([request]) => request.operation === "setExpanded");
    expect(resizeCalls).toEqual([[{ operation: "setExpanded", expanded: true }]]);
  });

  it("shows a readable error surface instead of the chat when the bridge is missing", async () => {
    await renderAssistant({ width: 2543, bridge: false });
    expect(container.textContent).toContain("当前窗口未启用个人助理桥");
    expect(container.querySelector('[data-expanded="true"]')).toBeNull();
    expect(container.querySelector('[data-expanded="false"]')).toBeNull();
    expect(container.querySelector(".desktop-assistant-chat-body")).toBeNull();
  });

  it("caps the chat body column only inside the wide media tier", () => {
    // The CSS wide tier and the initial-expansion tier stay one boundary.
    expect(launcherCss).toContain(`@media (min-width: ${LAUNCHER_ASSISTANT_WIDE_MIN_WIDTH}px)`);
    const mediaStart = launcherCss.indexOf(`@media (min-width: ${LAUNCHER_ASSISTANT_WIDE_MIN_WIDTH}px)`);
    expect(launcherCss.split("max-width: 920px").length - 1).toBe(1);
    expect(launcherCss.indexOf("max-width: 920px")).toBeGreaterThan(mediaStart);
    // Only the guarded compact body is capped; the floating window tier is not.
    const ruleStart = launcherCss.indexOf('[data-assistant-chat="compact"] .desktop-assistant-chat-body', mediaStart);
    expect(ruleStart).toBeGreaterThan(-1);
    const rule = launcherCss.slice(ruleStart, launcherCss.indexOf("}", ruleStart) + 1);
    expect(rule).toContain("width: 100%");
    expect(rule).toContain("max-width: 920px");
    expect(rule).toContain("margin-inline: auto");
  });
});
