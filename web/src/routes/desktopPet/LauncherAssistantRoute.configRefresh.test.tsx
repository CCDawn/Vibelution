// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { fetchJson } from "../../api/client";
import { launcherConversationApi } from "../../api/launcherAssistant";
import { queryKeys } from "../../api/queryKeys";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { useAppI18n } from "../../i18n/useAppI18n";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";

vi.mock("../../api/client", () => ({ fetchJson: vi.fn() }));
vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
let conversation: ConversationViewProps | undefined;
// Keep the real locale hook, runtime API and QueryClient observers. The heavy
// transcript renderer is replaced by its existing config-query contract only.
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    const { lang } = useAppI18n({ domains: ["chat"] });
    const config = useQuery({
      queryKey: [props.runtimeApi!.cacheKey, "config"],
      queryFn: ({ signal }) => props.runtimeApi!.fetchConfigBootstrap({ signal }), staleTime: 30_000,
    });
    return createElement("output", { "data-conversation-language": lang }, config.data?.modelLabels?.model || "model");
  },
}));

let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let nativeConfig: { language: "zh" | "en"; modelLabels: Record<string, string> };
let nativeDetail: Record<string, unknown>;
let invoke: ReturnType<typeof vi.fn>;
const modelConfigKey = [launcherConversationApi.cacheKey, "config"];
beforeAll(() => vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true));
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  client?.clear(); container?.remove(); conversation = undefined;
  vi.clearAllMocks(); vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}
async function pollCycle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 2_100)); });
  await settle();
}
async function click(label: string) {
  await act(async () => {
    const button = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
    expect(button).toBeTruthy(); button?.click();
  });
  await settle();
}
function calls(operation: string) {
  return invoke.mock.calls.filter(([request]) => request.operation === operation).length;
}
async function renderAssistant() {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  nativeConfig = { language: "zh", modelLabels: { model: "旧模型名称" } };
  nativeDetail = { id: "s", agentId: "a", status: "ready", messages: [] };
  invoke = vi.fn(async request => {
    switch (request.operation) {
      case "config": return nativeConfig;
      case "status": return { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" } };
      case "detail": return nativeDetail;
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "setExpanded": return { expanded: request.expanded };
      case "openLauncher": return { opened: true };
      case "send": return { accepted: true, turnId: "settings-turn" };
      default: throw new Error("unexpected_operation");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => { root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantRoute))); });
  await settle(); await settle();
}
async function sendSettingsRequest() {
  await click("展开个人助理聊天");
  await act(async () => conversation!.onComposerChange!("切换为英语并更新模型名称"));
  await act(async () => conversation!.onSubmit!());
  await settle();
}
function finishSettingsTurn() {
  nativeConfig = { language: "en", modelLabels: { model: "New model label" } };
  nativeDetail = { id: "s", agentId: "a", status: "ready", lastTurnTerminalTurnId: "settings-turn", terminalReason: "success", messages: [] };
}

describe("Launcher config refresh through real query cycles", () => {
  it("keeps the assistant default and opens Launcher by one explicit header action", async () => {
    await renderAssistant();
    expect(calls("openLauncher")).toBe(0);
    await click("展开个人助理聊天");
    const launcherButton = [...container.querySelectorAll("button")].find(button => button.textContent === "打开 Launcher");
    expect(launcherButton).toBeTruthy();
    await act(async () => { launcherButton!.click(); launcherButton!.click(); });
    await settle();
    expect(calls("openLauncher")).toBe(1);
    expect(calls("send")).toBe(0);
    expect(container.querySelector('[data-expanded="true"]')).toBeTruthy();
    expect(fetchJson).not.toHaveBeenCalled();
    invoke.mockImplementationOnce(async () => { throw new Error("入口暂不可用"); });
    await act(async () => launcherButton!.click()); await settle();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("入口暂不可用");
    expect(launcherButton!.disabled).toBe(false);
  });
  it("bootstraps the real shell locale through native config without HTTP", async () => {
    await renderAssistant();
    expect(client.getQueryData(queryKeys.configPublic())).toEqual(nativeConfig);
    expect(container.querySelector('button[aria-label="展开个人助理聊天"]')).toBeTruthy();
    expect(calls("config")).toBe(1);
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it("refreshes collapsed locale, marks inactive model config stale and reads labels on reopening", async () => {
    await renderAssistant(); await sendSettingsRequest();
    expect(container.querySelector("output")?.textContent).toBe("旧模型名称");
    await click("收起聊天");
    const configReads = calls("config");
    finishSettingsTurn(); await pollCycle();
    expect(container.querySelector('[data-expanded="false"]')).toBeTruthy();
    expect(container.querySelector('button[aria-label="Open assistant chat"]')).toBeTruthy();
    expect(client.getQueryData(queryKeys.configPublic())).toEqual(nativeConfig);
    expect(calls("config")).toBe(configReads + 1);
    expect(client.getQueryState(modelConfigKey)?.isInvalidated).toBe(true);
    expect(client.getQueryData(modelConfigKey)).toMatchObject({ modelLabels: { model: "旧模型名称" } });
    await click("Open assistant chat");
    expect(container.querySelector("output")?.textContent).toBe("New model label");
    expect(container.querySelector("output")?.getAttribute("data-conversation-language")).toBe("en");
    expect(calls("config")).toBe(configReads + 2);
    const settledReads = calls("config"); const detailReads = calls("detail");
    await pollCycle();
    expect(calls("config")).toBe(settledReads); expect(calls("detail")).toBe(detailReads);
    expect(calls("send")).toBe(1); expect(fetchJson).not.toHaveBeenCalled();
  }, 12_000);

  it("refreshes both active config keys once and ignores the same terminal on collapse/reopen", async () => {
    await renderAssistant(); await sendSettingsRequest();
    const configReads = calls("config");
    finishSettingsTurn(); await pollCycle();
    expect(calls("config")).toBe(configReads + 2);
    expect(container.querySelector("output")?.textContent).toBe("New model label");
    expect(container.querySelector("output")?.getAttribute("data-conversation-language")).toBe("en");
    await click("Collapse chat"); await click("Open assistant chat");
    expect(calls("config")).toBe(configReads + 2);
    const detailReads = calls("detail"); await pollCycle();
    expect(calls("detail")).toBe(detailReads); expect(calls("config")).toBe(configReads + 2);
    expect(calls("send")).toBe(1); expect(fetchJson).not.toHaveBeenCalled();
  }, 12_000);
});
