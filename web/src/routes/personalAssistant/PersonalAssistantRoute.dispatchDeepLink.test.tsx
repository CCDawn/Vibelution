// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchSessionDetail } from "../../api/chat";
import { fetchPersonalAssistant, fetchPersonalAssistantSettings } from "../../api/personalAssistant";
import { controlDesktopAssistant, getDesktopAssistantContext, setDesktopPetExpanded } from "../../api/desktopPet";
import { fetchPetActivity } from "../../api/pet";
import type { SessionDetail } from "../../api/types";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import { PersonalAssistantRoute } from "../PersonalAssistantRoute";

/**
 * 人工关注完成类通知的派遣深链：`?panel=dispatches` 必须直达派遣面板
 * （宽布局 = 右栏派遣 tab 激活；窄布局 = 直接打开派遣对话框）。
 * 独立文件：`personalassistantroute.test.tsx` 由并行会话 claim，不改动。
 */

vi.mock("../../api/chat", () => ({ fetchSessionDetail: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
vi.mock("../../api/personalAssistant", () => ({
  createPersonalAssistant: vi.fn(),
  fetchPersonalAssistant: vi.fn(),
  fetchPersonalAssistantSettings: vi.fn().mockResolvedValue({ settings: null }),
  updatePersonalAssistantSettings: vi.fn(),
  updatePersonalAssistantModel: vi.fn(),
}));
vi.mock("../../api/desktopPet", () => ({
  getDesktopAssistantContext: vi.fn(),
  setDesktopPetExpanded: vi.fn(),
  controlDesktopAssistant: vi.fn(),
}));
vi.mock("../../api/pet", () => ({ fetchPetActivity: vi.fn() }));
vi.mock("../../api/personalAssistantComputer", () => ({
  fetchPersonalAssistantComputer: vi.fn(async () => ({
    available: false, status: "idle", message: "", grantId: null, window: null, pending: null,
  })),
}));
vi.mock("../ChatCodingRoute", () => ({ ChatCodingRoute: () => <div data-native-session-chat="true" /> }));
vi.mock("./PersonalAssistantOverview", () => ({
  PersonalAssistantOverview: ({ headerAction }: { headerAction?: React.ReactNode }) => <div>{headerAction}概览</div>,
}));
vi.mock("./PersonalAssistantComputerPanel", () => ({
  PersonalAssistantComputerPanel: () => <div data-computer-panel="true" />,
}));
vi.mock("./PersonalAssistantAffairs", () => ({ PersonalAssistantAffairs: () => <div data-affairs-panel="true" /> }));
vi.mock("./PersonalAssistantDispatches", () => ({
  PersonalAssistantDispatches: () => <div data-dispatches-panel="true">派遣面板</div>,
}));
vi.mock("../desktopPet/WhaleRigCharacter", () => ({
  WhaleRigCharacter: () => <span>大肥鲸</span>,
}));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const assistant: PersonalAssistant = {
  agentId: "assistant-agent",
  directSessionId: "assistant-session",
  displayName: "个人助理",
  status: "active",
  setupStatus: "ready",
  profile: "personal_assistant_v1",
  renderer: "whale",
};

let root: Root, container: HTMLDivElement, client: QueryClient;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistant).mockResolvedValue({ assistant });
  vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue({ settings: null });
  vi.mocked(fetchSessionDetail).mockResolvedValue({
    id: assistant.directSessionId,
    agentId: assistant.agentId,
    sessionKind: "main",
  } as SessionDetail);
  vi.mocked(getDesktopAssistantContext).mockResolvedValue({ role: "desktop-assistant", mode: "assistant" });
  vi.mocked(setDesktopPetExpanded).mockResolvedValue({ expanded: true, width: 760, height: 600 });
  vi.mocked(fetchPetActivity).mockResolvedValue({
    schemaVersion: 1, aggregateTone: "idle", animationState: "idle",
    activeCount: 0, attentionCount: 0, generatedAt: "", sessions: [],
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  client.clear();
  vi.restoreAllMocks();
});

async function settle() {
  await act(async () => new Promise(resolve => setTimeout(resolve, 25)));
}

let router: ReturnType<typeof createMemoryRouter>;

async function render(path: string, innerWidth: number) {
  Object.defineProperty(window, "innerWidth", { value: innerWidth, configurable: true });
  vi.spyOn(window, "matchMedia").mockImplementation(query => ({
    matches: innerWidth <= 700 && query.includes("max-width"),
    media: query,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null,
  } as MediaQueryList));
  router = createMemoryRouter(
    [{ path: "/personal-assistant", element: <PersonalAssistantRoute /> }],
    { initialEntries: [path] },
  );
  await act(async () => root.render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  ));
  await settle();
  await settle();
}

describe("personal assistant dispatch deep link for completion notices", () => {
  it("wide layout: ?panel=dispatches activates the dispatches rail tab", async () => {
    await render("/personal-assistant?panel=dispatches", 1200);
    const tab = container.querySelector('[role="tab"][id$="dispatches"]');
    expect(tab?.getAttribute("data-state")).toBe("active");
    expect(container.querySelector('[data-dispatches-panel="true"]')).not.toBeNull();
  });

  it("narrow layout: ?panel=dispatches opens the dispatches dialog", async () => {
    await render("/personal-assistant?panel=dispatches", 640);
    // VDialog 走 Radix portal，内容挂在 document.body 而不是挂载容器里。
    expect(document.body.querySelector('[data-dispatches-panel="true"]')).not.toBeNull();
  });

  it("without the param the route keeps its default tab", async () => {
    await render("/personal-assistant", 1200);
    const overviewTab = container.querySelector('[role="tab"][id$="overview"]');
    expect(overviewTab?.getAttribute("data-state")).toBe("active");
    expect(container.querySelector('[data-dispatches-panel="true"]')).toBeNull();
  });

  it("switches to the dispatches tab when the param arrives after mount (SPA re-navigation)", async () => {
    // 通知卡点击走 react-router navigate：已在本页时组件不重挂载，
    // useState 初始化器不重跑，必须由 effect 响应 searchParams 变化。
    await render("/personal-assistant", 1200);
    expect(container.querySelector('[role="tab"][id$="overview"]')?.getAttribute("data-state")).toBe("active");
    await act(async () => router.navigate("/personal-assistant?panel=dispatches"));
    await settle();
    expect(container.querySelector('[role="tab"][id$="dispatches"]')?.getAttribute("data-state")).toBe("active");
    expect(container.querySelector('[data-dispatches-panel="true"]')).not.toBeNull();
  });

  it("re-arming the same param in-place does not toggle the tab away", async () => {
    await render("/personal-assistant?panel=dispatches", 1200);
    await act(async () => router.navigate("/personal-assistant?panel=dispatches"));
    await settle();
    // 同参二次导航效果幂等：仍是派遣 tab，不回跳 overview。
    expect(container.querySelector('[role="tab"][id$="dispatches"]')?.getAttribute("data-state")).toBe("active");
  });
});
