// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLauncherBranchInstances, selectLauncherProject } from "../../api/launcher";
import { getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus } from "../../api/launcherAssistant";
import { LauncherAssistantWorkspaceRoute } from "./LauncherAssistantWorkspaceRoute";

vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
vi.mock("../../api/launcher", () => ({
  getLauncherBranchInstances: vi.fn(), selectLauncherProject: vi.fn(),
  isLauncherProjectNotSelected: (error: unknown) => error instanceof Error && error.message === "not-selected",
}));
vi.mock("../../api/launcherAssistant", () => ({ getLauncherAssistantStatus: vi.fn(), getLauncherAssistantDetail: vi.fn(), getLauncherAssistantDispatches: vi.fn() }));
vi.mock("../../api/launcherAssistantComputer", () => ({ launcherAssistantComputer: { scope: "launcher" } }));
vi.mock("../../api/launcherAssistantPanels", () => ({ createLauncherAssistantPanelTransport: (agentId: string) => ({
  cacheKey: ["launcher-assistant", agentId], affairs: {}, preferences: {}, settings: {},
}) }));
vi.mock("../personalAssistant/PersonalAssistantAffairs", () => ({ PersonalAssistantAffairs: (props: any) => <div>{props.showHeading !== false ? <h2>待办与提醒</h2> : null}native affairs {props.agentId} {props.transport.cacheKey.join(":")}</div> }));
vi.mock("../personalAssistant/PersonalAssistantComputerPanel", () => ({ PersonalAssistantComputerPanel: (props: any) => <div>native computer {props.transport.scope}</div> }));
vi.mock("../personalAssistant/PersonalAssistantDialoguePreferences", () => ({ PersonalAssistantDialoguePreferences: (props: any) => <div>native preferences {props.agentId} {props.transport.cacheKey.join(":")}</div> }));
vi.mock("../personalAssistant/PersonalAssistantSettings", () => ({ PersonalAssistantSettings: (props: any) => <div>native settings {props.presentation} {props.transport.cacheKey.join(":")}</div> }));
vi.mock("./LauncherAssistantRoute", () => ({ LauncherAssistantRoute: (props: any) => <div data-computer-requested={String(Boolean(props.computerRequested))}>native dialogue{props.entryIntent ? <button>{props.entryIntent.label}</button> : null}</div> }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root, container: HTMLDivElement, client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getLauncherAssistantStatus).mockResolvedValue({ assistant: { agentId: "agent", directSessionId: "session", displayName: "小鲸" } });
  vi.mocked(getLauncherAssistantDetail).mockResolvedValue({ id: "session", messages: [{ id: "one" }, { id: "two" }] } as Awaited<ReturnType<typeof getLauncherAssistantDetail>>);
  vi.mocked(getLauncherAssistantDispatches).mockResolvedValue([]);
  vi.mocked(getLauncherBranchInstances).mockResolvedValue({ items: [] } as Awaited<ReturnType<typeof getLauncherBranchInstances>>);
  vi.mocked(selectLauncherProject).mockResolvedValue({ connected: true });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function render(panel: string) {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/launcher/assistant?panel=${panel}`]}>
    <LauncherAssistantWorkspaceRoute />
  </MemoryRouter></QueryClientProvider>));
  await act(async () => new Promise(resolve => setTimeout(resolve, 50)));
}

describe("Launcher assistant workspace", () => {
  it.each(["overview", "dispatches"])("falls back to dialogue for the removed %s page without its queries", async panel => {
    await render(panel);
    expect(container.textContent).toContain("native dialogue");
    expect(getLauncherAssistantStatus).not.toHaveBeenCalled();
    expect(getLauncherAssistantDetail).not.toHaveBeenCalled();
    expect(getLauncherAssistantDispatches).not.toHaveBeenCalled();
    expect(getLauncherBranchInstances).not.toHaveBeenCalled();
    expect(selectLauncherProject).not.toHaveBeenCalled();
  });
  it.each([
    ["affairs", "查看我的待办与提醒"],
    ["preferences", "查看当前对话偏好"],
    ["assistant-settings", "查看助理设置"],
    ["computer", "native dialogue"],
  ])("moves the legacy %s link into the conversation without loading its old page", async (panel, expected) => {
    await render(panel);
    expect(container.textContent).toContain(expected);
    expect(container.textContent).toContain("native dialogue");
    expect(getLauncherAssistantStatus).not.toHaveBeenCalled();
    expect(getLauncherAssistantDispatches).not.toHaveBeenCalled();
    expect(getLauncherBranchInstances).not.toHaveBeenCalled();
    expect(container.querySelector('[data-computer-requested="true"]') !== null).toBe(panel === "computer");
  });
});
