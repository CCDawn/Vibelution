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
vi.mock("../personalAssistant/PersonalAssistantAffairs", () => ({ PersonalAssistantAffairs: (props: any) => <div>native affairs {props.agentId} {props.transport.cacheKey.join(":")}</div> }));
vi.mock("../personalAssistant/PersonalAssistantComputerPanel", () => ({ PersonalAssistantComputerPanel: (props: any) => <div>native computer {props.transport.scope}</div> }));
vi.mock("../personalAssistant/PersonalAssistantDialoguePreferences", () => ({ PersonalAssistantDialoguePreferences: (props: any) => <div>native preferences {props.agentId} {props.transport.cacheKey.join(":")}</div> }));
vi.mock("../personalAssistant/PersonalAssistantSettings", () => ({ PersonalAssistantSettings: (props: any) => <div>native settings {props.presentation} {props.transport.cacheKey.join(":")}</div> }));
vi.mock("./LauncherAssistantRoute", () => ({ LauncherAssistantRoute: () => <div>native dialogue</div> }));
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
  it("shows only current assistant and connected project facts, with an actionable unselected state", async () => {
    vi.mocked(getLauncherBranchInstances).mockRejectedValueOnce(new Error("not-selected"))
      .mockResolvedValueOnce({ items: [{ id: "one" }] } as Awaited<ReturnType<typeof getLauncherBranchInstances>>);
    await render("overview");
    expect(container.textContent).toContain("当前助理与已连接项目");
    expect(container.textContent).toContain("小鲸");
    expect(container.textContent).toContain("会话消息");
    expect(container.textContent).toContain("尚未选择项目");
    const select = [...container.querySelectorAll("button")].find(button => button.textContent === "选择项目")!;
    await act(async () => select.click());
    await vi.waitFor(() => { expect(selectLauncherProject).toHaveBeenCalledOnce(); expect(getLauncherBranchInstances).toHaveBeenCalledTimes(2); });
    await act(async () => new Promise(resolve => setTimeout(resolve, 25)));
    expect(container.textContent).not.toContain("尚未选择项目");
    expect(getLauncherAssistantDetail).toHaveBeenCalledWith("session");
  });
  it("distinguishes a project error from no project", async () => {
    vi.mocked(getLauncherBranchInstances).mockRejectedValue(new Error("read failed"));
    await render("overview");
    expect(container.textContent).toContain("项目状态暂不可用");
    expect(container.textContent).toContain("read failed");
    expect(container.textContent).not.toContain("尚未选择项目");
  });
  it("shows real dispatch receipts and returns to dialogue to handle approvals", async () => {
    vi.mocked(getLauncherAssistantDispatches).mockResolvedValue([{ dispatchId: "dispatch-a", projectId: "project-a",
      receipt: { status: "running", resultSummary: "处理中", pendingApprovals: [{ approvalId: "a", toolName: "tool", risk: "high", targetSummary: {}, revision: "1", availableDecisions: ["accept"] }] } }]);
    await render("dispatches");
    expect(container.textContent).toContain("project-a");
    expect(container.textContent).toContain("处理中");
    await act(async () => ([...container.querySelectorAll("button")].find(button => button.textContent === "回到对话处理授权") as HTMLButtonElement).click());
    expect(container.textContent).toContain("native dialogue");
  });
  it.each([
    ["affairs", "native affairs agent launcher-assistant:agent"],
    ["preferences", "native preferences agent launcher-assistant:agent"],
    ["assistant-settings", "native settings page launcher-assistant:agent"],
    ["computer", "native computer launcher"],
  ])("binds %s to the native assistant surface", async (panel, expected) => {
    await render(panel);
    expect(container.textContent).toContain(expected);
    expect(getLauncherAssistantStatus).toHaveBeenCalled();
    expect(getLauncherBranchInstances).not.toHaveBeenCalled();
  });
});
