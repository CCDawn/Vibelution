// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPersonalAssistantOverview } from "../../api/personalAssistant";
import { queryKeys } from "../../api/queryKeys";
import { PersonalAssistantOverview } from "./PersonalAssistantOverview";
import routerSource from "../../app/router.tsx?raw";

vi.mock("../../api/personalAssistant", () => ({ fetchPersonalAssistantOverview: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, container: HTMLDivElement, client: QueryClient;
const openSession = vi.fn();
function CurrentLocation() { return <output>{useLocation().pathname}</output>; }
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue({ generatedAt: "2026-10-14T01:00:00Z",
    counts: { agents: 1, sessions: 1, running: 1, waiting: 0, failed: 0 }, agents: [], attention: [],
    sessions: [{ id: "worker-session", agentId: "worker-agent", title: "平台任务", status: "running", currentPhase: "tooling" }] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  client.setQueryDefaults(queryKeys.configPublic(), { staleTime: Infinity });
  client.setQueryData(queryKeys.configPublic(), { language: "zh" });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function render(desktop = false, showTitles = true) {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter>
    <PersonalAssistantOverview desktop={desktop} showTitles={showTitles} onOpenSession={openSession} /><CurrentLocation />
  </MemoryRouter></QueryClientProvider>));
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
}
describe("personal assistant management shortcuts", () => {
  it("updates interface copy and statuses when language changes without translating user titles", async () => {
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue({ generatedAt: "", counts: { agents: 1, sessions: 9, running: 1, waiting: 0, failed: 0 },
      agents: [{ id: "custom-agent", displayName: "我的智能体", status: "idle" }], attention: [],
      sessions: Array.from({ length: 9 }, (_, i) => ({ id: `s-${i}`, agentId: "custom-agent", title: `用户自定义 ${i}`, status: "running", currentPhase: "tooling" })) });
    await render();
    expect(container.querySelector("h2")?.textContent).toBe("平台概览");
    await act(async () => { client.setQueryData(queryKeys.configPublic(), { language: "en" }); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(container.querySelector("h2")?.textContent).toBe("Platform overview");
    expect(container.querySelector('[aria-label="Refresh platform overview"]')).not.toBeNull();
    expect(container.querySelector('a[href="/agents"]')?.textContent).toBe("Agents");
    expect(container.querySelector('[role="tab"][id$="attention"]')?.textContent).toBe("Attention 0");
    await act(async () => (container.querySelector('[role="tab"][id$="sessions"]') as HTMLElement).dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(container.querySelector('input[aria-label="Search sessions"]')?.getAttribute("placeholder")).toBe("Search sessions…");
    expect(container.textContent).toContain("Page 1 / 2");
    expect(container.textContent).toContain("9 items");
    expect(container.querySelector("li")?.textContent).toContain("用户自定义 0Using tools");
    expect([...container.querySelectorAll("button")].some(button => button.textContent === "Next")).toBe(true);
    await act(async () => { client.setQueryData(queryKeys.configPublic(), { language: "zh" }); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(container.querySelector("h2")?.textContent).toBe("平台概览");
    expect(container.querySelector('input[aria-label="搜索会话"]')?.getAttribute("placeholder")).toBe("搜索会话…");
    expect(container.textContent).toContain("第 1 / 2 页");
    expect(container.querySelector("li")?.textContent).toContain("用户自定义 0操作工具中");
    expect([...container.querySelectorAll("button")].some(button => button.textContent === "下一页")).toBe(true);
    await act(async () => (container.querySelector('[role="tab"][id$="agents"]') as HTMLElement).dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await act(async () => { client.setQueryData(queryKeys.configPublic(), { language: "en" }); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(container.querySelector("li")?.textContent).toContain("我的智能体Idle");
    expect(container.querySelector('input[aria-label="Search Agents"]')).not.toBeNull();
  });

  it("localizes hidden titles and attention statuses while preserving Session navigation", async () => {
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue({ generatedAt: "", counts: { agents: 0, sessions: 1, running: 0, waiting: 1, failed: 0 },
      agents: [], attention: [{ id: "attention", title: "私人待办", kind: "approval", sessionId: "worker-session" }],
      sessions: [{ id: "worker-session", agentId: "a", title: "私人任务", status: "ready", currentPhase: "ready" }] });
    client.setQueryData(queryKeys.configPublic(), { language: "en" });
    await render(true, false);
    expect(container.textContent).not.toMatch(/私人待办|私人任务/);
    expect(container.querySelector("li")?.textContent).toContain("Item 1Awaiting confirmation");
    await act(async () => container.querySelector<HTMLButtonElement>("li button")?.click());
    expect(openSession).toHaveBeenCalledWith("worker-session");
    await act(async () => (container.querySelector('[role="tab"][id$="sessions"]') as HTMLElement).dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(container.querySelector("li")?.textContent).toContain("Session 1Ready");
  });

  it("links all platform management entry points to registered owner pages", async () => {
    await render();
    const links = [...container.querySelectorAll("a")].map(link => [link.textContent, link.getAttribute("href")]);
    expect(links).toEqual([
      ["智能体", "/agents"], ["后台任务", "/aux"], ["配置", "/config"], ["运行诊断", "/logs"],
    ]);
    for (const [, path] of links) expect(routerSource).toContain(`path: "${path!.slice(1)}"`);
    const more = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("更多管理"))!;
    await act(async () => more.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerType: "mouse" })));
    const items = [...document.querySelectorAll('[role="menuitem"]')];
    expect(items.map(item => item.textContent)).toEqual(["团队管理", "工具管理", "记忆管理", "知识管理"]);
    await act(async () => (items[0] as HTMLElement).click());
    expect(container.querySelector("output")?.textContent).toBe("/teams");
  });
  it("keeps desktop navigation with the owner workbench Session callback", async () => {
    await render(true);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    await act(async () => (container.querySelector('[role="tab"][id$="sessions"]') as HTMLElement).dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    const session = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("平台任务"))!;
    await act(async () => session.click());
    expect(openSession).toHaveBeenCalledWith("worker-session");
    expect(container.textContent).toContain("操作工具中");
  });
  it("routes human-attention rows without a session to their target page", async () => {
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue({ generatedAt: "",
      counts: { agents: 0, sessions: 0, running: 0, waiting: 0, failed: 0 }, agents: [], sessions: [], attention: [],
      humanAttention: [{ id: "escalation:stagetask-1", title: "研究异常已升级", kind: "anomaly", severity: "critical", targetUrl: "/teams?researchView=workflow" }] });
    await render();
    const row = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("研究异常已升级"))!;
    await act(async () => row.click());
    expect(openSession).not.toHaveBeenCalled();
    expect(container.querySelector("output")?.textContent).toBe("/teams");
  });
  it("hides private titles and Agent names throughout the desktop overview without breaking navigation", async () => {
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue({ generatedAt: "",
      counts: { agents: 1, sessions: 1, running: 1, waiting: 1, failed: 0 },
      agents: [{ id: "private-agent", displayName: "私人智能体", status: "idle" }],
      attention: [{ id: "private-attention", title: "私人待办", sessionId: "worker-session", kind: "approval" }],
      sessions: [{ id: "worker-session", agentId: "private-agent", title: "私人任务", status: "running", currentPhase: "tooling" }] });
    await render(true, false);
    expect(container.textContent).not.toMatch(/私人智能体|私人待办|私人任务/);
    expect(container.textContent).toContain("事项 1");
    const attention = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("事项 1"))!;
    await act(async () => attention.click());
    expect(openSession).toHaveBeenCalledWith("worker-session");
    await act(async () => (container.querySelector('[role="tab"][id$="sessions"]') as HTMLElement).dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    const session = [...container.querySelectorAll("button")].find(button => button.textContent?.startsWith("会话 1就绪") || button.textContent?.startsWith("会话 1操作工具中"))!;
    await act(async () => session.click());
    expect(openSession).toHaveBeenCalledWith("worker-session");
  });
  it("shows eight sessions per page with search and status filters", async () => {
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue({ generatedAt: "", counts: { agents: 0, sessions: 19, running: 1, waiting: 0, failed: 0 }, agents: [], attention: [],
      sessions: Array.from({ length: 19 }, (_, i) => ({ id: `s-${i}`, agentId: "a", title: `任务 ${i}`, status: i === 0 ? "running" : "ready", currentPhase: i === 0 ? "tooling" : "ready" })) });
    await render();
    expect(container.querySelectorAll("li")).toHaveLength(0);
    await act(async () => (container.querySelector('[role="tab"][id$="sessions"]') as HTMLElement).dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(container.querySelectorAll("li")).toHaveLength(8);
    const next = [...container.querySelectorAll("button")].find(button => button.textContent === "下一页")!;
    await act(async () => next.click());
    expect(container.querySelector("li")?.textContent).toContain("任务 8");
    const search = container.querySelector('input[aria-label="搜索会话"]') as HTMLInputElement;
    await act(async () => { const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!; setter.call(search, "任务 18"); search.dispatchEvent(new Event("input", { bubbles: true })); });
    expect(container.querySelectorAll("li")).toHaveLength(1);
    const running = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("运行中 1"))!;
    await act(async () => running.click());
    expect(container.querySelectorAll("li")).toHaveLength(1);
    expect(container.querySelector("li")?.textContent).toContain("任务 0");
  });
});
