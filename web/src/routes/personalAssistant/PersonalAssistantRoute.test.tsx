// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchSessionDetail } from "../../api/chat";
import { createPersonalAssistant, fetchPersonalAssistant } from "../../api/personalAssistant";
import { getDesktopAssistantContext, setDesktopPetExpanded } from "../../api/desktopPet";
import { fetchPetActivity } from "../../api/pet";
import type { PetActivity } from "../../api/types/petActivity";
import type { SessionDetail } from "../../api/types";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import { PersonalAssistantRoute } from "../PersonalAssistantRoute";
import { DesktopAssistantRoute } from "../desktopPet/DesktopAssistantRoute";

vi.mock("../../api/chat", () => ({ fetchSessionDetail: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
vi.mock("../../api/personalAssistant", () => ({ createPersonalAssistant: vi.fn(), fetchPersonalAssistant: vi.fn() }));
vi.mock("../../api/desktopPet", () => ({ getDesktopAssistantContext: vi.fn(), setDesktopPetExpanded: vi.fn(), controlDesktopAssistant: vi.fn() }));
vi.mock("../../api/pet", () => ({ fetchPetActivity: vi.fn() }));
vi.mock("../ChatCodingRoute", () => ({ ChatCodingRoute: () => <div data-native-session-chat="true" /> }));
vi.mock("./PersonalAssistantOverview", () => ({ PersonalAssistantOverview: () => <div>真实概览入口</div> }));
vi.mock("../desktopPet/WhaleRigCharacter", () => ({ WhaleRigCharacter: ({ tone, animationState }: { tone: string; animationState: string }) => <span data-whale-tone={tone} data-whale-animation={animationState}>大肥鲸</span> }));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const assistant: PersonalAssistant = { agentId: "assistant-agent", directSessionId: "assistant-session", displayName: "个人助理",
  status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" };
let root: Root, container: HTMLDivElement, client: QueryClient;
function Location() { const location = useLocation(); return <output>{location.pathname}{location.search}</output>; }
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistant).mockResolvedValue({ assistant });
  vi.mocked(createPersonalAssistant).mockResolvedValue({ assistant });
  vi.mocked(fetchSessionDetail).mockResolvedValue({ id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "main" } as SessionDetail);
  vi.mocked(getDesktopAssistantContext).mockResolvedValue({ role: "desktop-assistant", mode: "assistant" });
  vi.mocked(setDesktopPetExpanded).mockResolvedValue({ expanded: true, width: 760, height: 600 });
  vi.mocked(fetchPetActivity).mockResolvedValue({ schemaVersion: 1, aggregateTone: "idle", animationState: "idle", activeCount: 0, attentionCount: 0, generatedAt: "", sessions: [] });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }
async function render(path: string, desktop = false) {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>
    {desktop ? <DesktopAssistantRoute /> : <PersonalAssistantRoute />}<Location />
  </MemoryRouter></QueryClientProvider>));
  await settle(); await settle();
}
describe("personal assistant page admission", () => {
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
  it("keeps the whale collapsed when native expansion fails", async () => {
    vi.mocked(setDesktopPetExpanded).mockRejectedValue(new Error("桌面壳需要更新"));
    await render("/desktop-assistant", true);
    await act(async () => (container.querySelector('[aria-label="展开个人助理聊天"]') as HTMLButtonElement).click()); await settle();
    expect(container.querySelector("[data-native-session-chat]")).toBeNull();
    expect(container.querySelector('[data-expanded="false"]')).not.toBeNull();
    expect(container.textContent).toContain("桌面壳需要更新");
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
});
