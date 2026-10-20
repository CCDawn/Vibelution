// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchSessionDetail } from "../../api/chat";
import { createPersonalAssistant, fetchPersonalAssistant, fetchPersonalAssistantSettings } from "../../api/personalAssistant";
import { controlDesktopAssistant, getDesktopAssistantContext, setDesktopPetExpanded } from "../../api/desktopPet";
import { fetchPetActivity } from "../../api/pet";
import { queryKeys } from "../../api/queryKeys";
import type { PetActivity } from "../../api/types/petActivity";
import type { SessionDetail } from "../../api/types";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import { PersonalAssistantRoute } from "../PersonalAssistantRoute";
import { DesktopAssistantRoute } from "../desktopPet/DesktopAssistantRoute";

vi.mock("../../api/chat", () => ({ fetchSessionDetail: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
vi.mock("../../api/personalAssistant", () => ({ createPersonalAssistant: vi.fn(), fetchPersonalAssistant: vi.fn(),
  fetchPersonalAssistantSettings: vi.fn().mockResolvedValue({ settings: null }),
  updatePersonalAssistantSettings: vi.fn().mockResolvedValue({ settings: null }),
  updatePersonalAssistantModel: vi.fn(),
}));
vi.mock("../../api/desktopPet", () => ({ getDesktopAssistantContext: vi.fn(), setDesktopPetExpanded: vi.fn(), controlDesktopAssistant: vi.fn() }));
vi.mock("../../api/pet", () => ({ fetchPetActivity: vi.fn() }));
vi.mock("../../api/personalAssistantComputer", () => ({ fetchPersonalAssistantComputer: vi.fn(async () => ({
  available: false, status: "idle", message: "", grantId: null, window: null, pending: null,
})) }));
vi.mock("../ChatCodingRoute", () => ({ ChatCodingRoute: () => <div data-native-session-chat="true" /> }));
vi.mock("./PersonalAssistantOverview", () => ({ PersonalAssistantOverview: ({ headerAction }: { headerAction?: React.ReactNode }) => <div>{headerAction}真实概览入口</div> }));
vi.mock("./PersonalAssistantComputerPanel", () => ({ PersonalAssistantComputerPanel: ({ active, onCollapse }: { active: boolean; onCollapse: () => void }) =>
  <div data-computer-panel={String(active)}><button onClick={onCollapse}>收起电脑操作栏</button></div> }));
vi.mock("./PersonalAssistantAffairs", () => ({ PersonalAssistantAffairs: () => <div data-affairs-panel="true">事务面板</div> }));
vi.mock("../desktopPet/WhaleRigCharacter", () => ({ WhaleRigCharacter: ({ tone, animationState }: { tone: string; animationState: string }) => <span data-whale-tone={tone} data-whale-animation={animationState}>大肥鲸</span> }));
const locale = vi.hoisted(() => ({ lang: "zh" as "zh" | "en" }));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: locale.lang }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const assistant: PersonalAssistant = { agentId: "assistant-agent", directSessionId: "assistant-session", displayName: "个人助理",
  status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" };
let root: Root, container: HTMLDivElement, client: QueryClient;
function Location() { const location = useLocation(); return <output>{location.pathname}{location.search}</output>; }
beforeEach(() => {
  vi.clearAllMocks();
  locale.lang = "zh";
  vi.mocked(fetchPersonalAssistant).mockResolvedValue({ assistant });
  vi.mocked(createPersonalAssistant).mockResolvedValue({ assistant });
  vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue({ settings: null });
  vi.mocked(fetchSessionDetail).mockResolvedValue({ id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "main" } as SessionDetail);
  vi.mocked(getDesktopAssistantContext).mockResolvedValue({ role: "desktop-assistant", mode: "assistant" });
  vi.mocked(setDesktopPetExpanded).mockResolvedValue({ expanded: true, width: 760, height: 600 });
  vi.mocked(fetchPetActivity).mockResolvedValue({ schemaVersion: 1, aggregateTone: "idle", animationState: "idle", activeCount: 0, attentionCount: 0, generatedAt: "", sessions: [] });
  Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
  vi.spyOn(window, "matchMedia").mockImplementation(query => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null } as MediaQueryList));
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); vi.restoreAllMocks(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }
async function render(path: string, desktop = false) {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>
    {desktop ? <DesktopAssistantRoute /> : <PersonalAssistantRoute />}<Location />
  </MemoryRouter></QueryClientProvider>));
  await settle(); await settle();
}
describe("personal assistant page admission", () => {
  it("switches rail labels in both directions without replacing the native session", async () => {
    await render("/personal-assistant");
    const chat = container.querySelector("[data-native-session-chat]");
    expect(container.querySelector('[aria-label="助理侧栏"]')).not.toBeNull();
    locale.lang = "en";
    await render("/personal-assistant");
    expect(container.querySelector('[aria-label="Assistant sidebar"]')).not.toBeNull();
    expect(container.querySelector('[role="tab"][id$="overview"]')?.textContent).toContain("Platform overview");
    expect(container.querySelector('[role="tab"][id$="computer"]')?.textContent).toContain("Computer control");
    expect(container.querySelector('[role="tab"][id$="preferences"]')?.textContent).toContain("Dialogue preferences");
    expect(container.querySelector('[role="tab"][id$="affairs"]')?.textContent).toContain("Affairs");
    expect(container.querySelector('[aria-label="Collapse platform overview"]')).not.toBeNull();
    expect(container.querySelector("[data-native-session-chat]")).toBe(chat);
    expect(container.querySelector("output")?.textContent).toContain("session=assistant-session");
    expect(createPersonalAssistant).not.toHaveBeenCalled();
    locale.lang = "zh";
    await render("/personal-assistant");
    expect(container.querySelector('[aria-label="助理侧栏"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="收起平台概览"]')).not.toBeNull();
  });
  it("switches narrow entries and an existing desktop error when language changes", async () => {
    Object.defineProperty(window, "innerWidth", { value: 390, configurable: true });
    vi.mocked(window.matchMedia).mockImplementation(query => ({ matches: true, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null } as MediaQueryList));
    vi.mocked(controlDesktopAssistant).mockResolvedValue({ busyElsewhere: true } as Awaited<ReturnType<typeof controlDesktopAssistant>>);
    await render("/personal-assistant");
    await act(async () => ([...container.querySelectorAll("button")].find(row => row.textContent === "桌面模式") as HTMLButtonElement).click());
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("另一个工作台");
    locale.lang = "en";
    await render("/personal-assistant");
    expect(container.querySelector('[aria-label="Personal assistant actions"]')).not.toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("another workbench");
    const overview = [...container.querySelectorAll("button")].find(row => row.textContent === "Platform overview") as HTMLButtonElement;
    await act(async () => overview.click());
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Platform overview");
    expect(controlDesktopAssistant).toHaveBeenCalledTimes(1);
  });
  it("mounts the affairs panel from the rail tab", async () => {
    await render("/personal-assistant");
    expect(container.querySelector("[data-affairs-panel]")).toBeNull();
    await act(async () => (container.querySelector('[role="tab"][id$="affairs"]') as HTMLElement).dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await settle();
    expect(container.querySelector("[data-affairs-panel]")?.getAttribute("data-affairs-panel")).toBe("true");
  });
  it("opens the existing name/model settings from the real workbench entry", async () => {
    vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue({ settings: {
      displayName: "个人助理", preferencesConfigured: true,
      preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" },
      model: { currentModelId: "", choices: [] },
    } });
    await render("/personal-assistant");
    const button = [...container.querySelectorAll("button")].find(node => node.textContent?.includes("助理设置"))!;
    await act(async () => button.click()); await settle();
    expect(document.querySelector('input[aria-label="助理名称"]')).not.toBeNull();
    expect(document.body.textContent).toContain("对话模型");
  });
  it("switches the right rail to computer controls while preserving native chat and character", async () => {
    await render("/personal-assistant");
    expect(container.querySelector("[data-computer-panel]")).toBeNull();
    await act(async () => (container.querySelector('[role="tab"][id$="computer"]') as HTMLElement).dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await settle();
    expect(container.querySelector('[data-computer-panel="true"]')).not.toBeNull();
    expect(container.querySelector("[data-native-session-chat]")).not.toBeNull();
    expect(container.querySelector('aside[aria-label="个人助理角色"]')).not.toBeNull();
    await act(async () => ([...container.querySelectorAll("button")].find(row => row.textContent === "收起电脑操作栏") as HTMLButtonElement).click());
    await settle();
    expect(container.querySelector('[aria-label="展开平台概览"]')).not.toBeNull();
    expect(container.querySelector("[data-native-session-chat]")).not.toBeNull();
  });
  it("opens computer controls in a narrow dialog and retains its top entry after collapse", async () => {
    Object.defineProperty(window, "innerWidth", { value: 390, configurable: true });
    vi.mocked(window.matchMedia).mockImplementation(query => ({ matches: true, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null } as MediaQueryList));
    await render("/personal-assistant");
    const open = [...container.querySelectorAll("button")].find(row => row.textContent === "电脑操作")!;
    await act(async () => open.click()); await settle();
    expect(document.querySelector('[role="dialog"] [data-computer-panel="true"]')).not.toBeNull();
    await act(async () => ([...document.querySelectorAll('[role="dialog"] button')].find(row => row.textContent === "收起电脑操作栏") as HTMLButtonElement).click()); await settle();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector("[data-native-session-chat]")).not.toBeNull();
    expect(open.isConnected).toBe(true);
  });
  it("bootstraps a bare entry to the same canonical session and mounts the native host", async () => {
    await render("/personal-assistant");
    expect(container.querySelector("output")?.textContent).toBe("/personal-assistant?session=assistant-session");
    expect(container.querySelector("[data-native-session-chat]")).not.toBeNull();
    expect(createPersonalAssistant).not.toHaveBeenCalled();
    expect(fetchSessionDetail).toHaveBeenCalledWith("assistant-session", expect.objectContaining({ transcriptScope: "none", includeSecondary: false }));
  });
  it("provisions the singleton only when discovery reports it missing", async () => {
    vi.mocked(fetchPersonalAssistant).mockResolvedValue({ assistant: null });
    await render("/personal-assistant");
    expect(createPersonalAssistant).toHaveBeenCalledTimes(1);
    expect(container.querySelector("[data-native-session-chat]")).not.toBeNull();
  });
  it("shows a recoverable state when provisioning leaves the assistant unready", async () => {
    vi.mocked(fetchPersonalAssistant).mockResolvedValue({ assistant: null });
    vi.mocked(createPersonalAssistant).mockResolvedValue({ assistant: { ...assistant, setupStatus: "setup_required" } });
    await render("/personal-assistant");
    expect(container.querySelector("[data-native-session-chat]")).toBeNull();
    expect(container.textContent).toContain("个人助理需要恢复");
    expect(fetchSessionDetail).not.toHaveBeenCalled();
  });
  it.each(["?session=another-session", "?session=assistant-session&companion=virtual-person", "?room=team"])("blocks incompatible route identity %s", async search => {
    await render(`/personal-assistant${search}`);
    expect(container.querySelector("[data-native-session-chat]")).toBeNull();
    expect(container.textContent).toContain("会话与个人助理身份不匹配");
  });
  it("blocks a native Session whose Agent differs from the singleton", async () => {
    vi.mocked(fetchSessionDetail).mockResolvedValue({ id: assistant.directSessionId, agentId: "another-agent" } as SessionDetail);
    await render("/personal-assistant?session=assistant-session");
    expect(container.querySelector("[data-native-session-chat]")).toBeNull();
    expect(container.textContent).toContain("原生会话与个人助理身份不匹配");
  });
  it("does not provision or mount chat when the native desktop context is unavailable", async () => {
    vi.mocked(getDesktopAssistantContext).mockRejectedValue(new Error("桌面壳需要更新"));
    await render("/desktop-assistant?session=assistant-session", true);
    expect(fetchPersonalAssistant).not.toHaveBeenCalled();
    expect(fetchPetActivity).not.toHaveBeenCalled();
    expect(createPersonalAssistant).not.toHaveBeenCalled();
    expect(container.querySelector("[data-native-session-chat]")).toBeNull();
    expect(container.textContent).toContain("桌面壳需要更新");
  });
  it("keeps desktop chat on its canonical Session and opens only after a successful native resize", async () => {
    await render("/desktop-assistant", true);
    expect(container.querySelector("[data-native-session-chat]")).toBeNull();
    await act(async () => (container.querySelector('[aria-label="展开个人助理聊天"]') as HTMLButtonElement).click()); await settle();
    expect(setDesktopPetExpanded).toHaveBeenCalledWith(true);
    expect(container.querySelector("[data-native-session-chat]")).not.toBeNull();
    expect(container.querySelector("output")?.textContent).toBe("/desktop-assistant?session=assistant-session");
  });
  it("verifies a server window once and makes it reusable by native chat", async () => {
    const detail = { id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "main", messages: [], transcriptScope: "window" } as SessionDetail;
    vi.mocked(fetchSessionDetail).mockResolvedValue(detail);
    await render("/desktop-assistant", true);
    expect(fetchSessionDetail).toHaveBeenCalledWith(assistant.directSessionId, expect.objectContaining({ transcriptScope: "window", messageLimit: 40, includeSecondary: true }));
    expect(client.getQueryData(queryKeys.session(assistant.directSessionId))).toEqual(detail);
    const nativeChatFetch = vi.fn().mockResolvedValue(detail);
    const cached = await client.fetchQuery({ queryKey: queryKeys.session(assistant.directSessionId), queryFn: nativeChatFetch, staleTime: 1500 });
    expect(cached).toEqual(detail);
    expect(nativeChatFetch).not.toHaveBeenCalled();
  });
  it("does not admit chat from a fresh optimistic shell when the server binding is wrong", async () => {
    client.setQueryData(queryKeys.session(assistant.directSessionId), { id: assistant.directSessionId, agentId: assistant.agentId,
      sessionKind: "main", provisionalTranscript: true, messages: [] });
    vi.mocked(fetchSessionDetail).mockResolvedValue({ id: assistant.directSessionId, agentId: "other", sessionKind: "main" } as SessionDetail);
    await render("/desktop-assistant", true);
    await act(async () => (container.querySelector('[aria-label="展开个人助理聊天"]') as HTMLButtonElement).click()); await settle();
    expect(fetchSessionDetail).toHaveBeenCalled();
    expect(container.querySelector('[data-native-session-chat]')).toBeNull();
  });
  it("keeps the whale collapsed when native expansion fails", async () => {
    vi.mocked(setDesktopPetExpanded).mockRejectedValue(new Error("桌面壳需要更新"));
    await render("/desktop-assistant", true);
    await act(async () => (container.querySelector('[aria-label="展开个人助理聊天"]') as HTMLButtonElement).click()); await settle();
    expect(container.querySelector("[data-native-session-chat]")).toBeNull();
    expect(container.querySelector('[data-expanded="false"]')).not.toBeNull();
    expect(container.textContent).toContain("桌面壳需要更新");
  });
  it("closes only the chat and returns to the desktop character", async () => {
    const close = vi.spyOn(window, "close").mockImplementation(() => {});
    await render("/desktop-assistant", true);
    await act(async () => (container.querySelector('[aria-label="展开个人助理聊天"]') as HTMLButtonElement).click()); await settle();
    await act(async () => (container.querySelector('[data-expanded="true"] [aria-label="关闭聊天"]') as HTMLButtonElement).click()); await settle();
    expect(setDesktopPetExpanded).toHaveBeenLastCalledWith(false);
    expect(container.querySelector('[data-expanded="false"]')).not.toBeNull();
    expect(container.querySelector('[data-native-session-chat]')).toBeNull();
    expect(close).not.toHaveBeenCalled();
  });
  it("keeps chat and shows the error if returning to the character fails", async () => {
    const close = vi.spyOn(window, "close").mockImplementation(() => {});
    await render("/desktop-assistant", true);
    await act(async () => (container.querySelector('[aria-label="展开个人助理聊天"]') as HTMLButtonElement).click()); await settle();
    vi.mocked(setDesktopPetExpanded).mockRejectedValueOnce(new Error("窗口调整失败"));
    await act(async () => (container.querySelector('[data-expanded="true"] [aria-label="关闭聊天"]') as HTMLButtonElement).click()); await settle();
    expect(container.querySelector('[data-expanded="true"]')).not.toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("窗口调整失败");
    expect(close).not.toHaveBeenCalled();
  });
  it.each([
    ["running", "tooling", "正在陪你工作"], ["approval", "waiting", "需要你确认"], ["error", "alert", "有任务遇到问题"],
  ] as const)("reflects the native platform %s projection while collapsed", async (aggregateTone, animationState, label) => {
    vi.mocked(fetchPetActivity).mockResolvedValue({ schemaVersion: 1, aggregateTone, animationState, activeCount: 1, attentionCount: 1, generatedAt: "", sessions: [] } satisfies PetActivity);
    await render("/desktop-assistant", true);
    expect(container.querySelector(`[data-whale-tone="${aggregateTone}"][data-whale-animation="${animationState}"]`)).not.toBeNull();
    expect(container.textContent).toContain(label);
    expect(container.querySelector("[data-native-session-chat]")).toBeNull();
  });
  it("makes activity read failure visible instead of claiming the platform is idle", async () => {
    vi.mocked(fetchPetActivity).mockRejectedValue(new Error("offline"));
    await render("/desktop-assistant", true);
    expect(container.textContent).toContain("暂时无法读取平台状态");
    expect(container.textContent).not.toContain("在这里等你");
  });
  it("places the character in the workbench sidebar and reflects platform work phases", async () => {
    vi.mocked(fetchPetActivity).mockResolvedValue({ schemaVersion: 1, aggregateTone: "running", animationState: "thinking", activeCount: 1,
      attentionCount: 0, generatedAt: "", sessions: [{ sessionId: "worker", title: "Worker", agentId: "worker", agentDisplayName: "Worker", tone: "running", phase: "thinking", updatedAt: "" }] });
    await render("/personal-assistant");
    expect(container.querySelector('aside[aria-label="个人助理角色"]')).not.toBeNull();
    expect(container.querySelector('[data-whale-animation="thinking"]')).not.toBeNull();
    expect(container.textContent).toContain("思考中");
  });
  it("keeps the expanded desktop window focused on the same native chat", async () => {
    await render("/desktop-assistant", true);
    await act(async () => (container.querySelector('[aria-label="展开个人助理聊天"]') as HTMLButtonElement).click()); await settle();
    expect(container.querySelector('[data-assistant-chat="compact"]')).not.toBeNull();
    expect(container.querySelector('[data-native-session-chat]')).not.toBeNull();
    expect(container.textContent).not.toContain("真实概览入口");
    expect(container.querySelector('[aria-label="实时对话"]')).toBeNull();
  });
  it("announces a native final reply once, preserves approval priority, and clears on focused viewing", async () => {
    await render("/desktop-assistant", true);
    const reply = { id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "main", messages: [{ role: "assistant", status: "completed", turnId: "reply-turn", turnItems: [
      { type: "agent_message", phase: "final_answer", status: "completed", itemId: "reply-item", text: "Done" },
    ] }] } as SessionDetail;
    await act(async () => client.setQueryData(queryKeys.personalAssistantReplies(assistant.agentId, assistant.directSessionId), reply));
    await settle();
    expect(container.textContent).toContain("有 1 条新消息");
    await act(async () => client.setQueryData(queryKeys.personalAssistantReplies(assistant.agentId, assistant.directSessionId), { ...reply, updatedAt: "clock-only" }));
    expect(container.textContent).not.toContain("有 2 条新消息");
    await act(async () => client.setQueryData(queryKeys.petActivity(), { schemaVersion: 1, aggregateTone: "approval", animationState: "waiting", activeCount: 1, attentionCount: 1, generatedAt: "", sessions: [] }));
    await settle();
    expect(container.querySelector('[data-whale-animation="waiting"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="1 条未读提醒"]')).not.toBeNull();
    const focus = vi.spyOn(document, "hasFocus").mockReturnValue(true);
    await act(async () => (container.querySelector('[aria-label="展开个人助理聊天"]') as HTMLButtonElement).click()); await settle();
    expect(container.querySelector('[aria-label="1 条未读提醒"]')).toBeNull();
    focus.mockRestore();
  });
});
