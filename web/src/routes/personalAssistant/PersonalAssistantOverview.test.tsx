// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPersonalAssistantOverview } from "../../api/personalAssistant";
import { PersonalAssistantOverview } from "./PersonalAssistantOverview";
import routerSource from "../../app/router.tsx?raw";

vi.mock("../../api/personalAssistant", () => ({ fetchPersonalAssistantOverview: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, container: HTMLDivElement, client: QueryClient;
const openSession = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue({ generatedAt: "2026-10-14T01:00:00Z",
    counts: { agents: 1, sessions: 1, running: 1, waiting: 0, failed: 0 }, agents: [], attention: [],
    sessions: [{ id: "worker-session", agentId: "worker-agent", title: "平台任务", status: "running", currentPhase: "tooling" }] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function render(desktop = false, showTitles = true) {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter>
    <PersonalAssistantOverview desktop={desktop} showTitles={showTitles} onOpenSession={openSession} />
  </MemoryRouter></QueryClientProvider>));
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
}
describe("personal assistant management shortcuts", () => {
  it("links all platform management entry points to registered owner pages", async () => {
    await render();
    const links = [...container.querySelectorAll("a")].map(link => [link.textContent, link.getAttribute("href")]);
    expect(links).toEqual([
      ["智能体管理", "/agents"], ["后台任务", "/aux"], ["记忆管理", "/memory"], ["工具管理", "/agents/tools"],
      ["团队管理", "/teams"], ["知识管理", "/memory/knowledge"], ["配置管理", "/config"], ["运行诊断", "/logs"],
    ]);
    for (const [, path] of links) expect(routerSource).toContain(`path: "${path!.slice(1)}"`);
  });
  it("keeps desktop navigation with the owner workbench Session callback", async () => {
    await render(true);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    const session = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("平台任务"))!;
    await act(async () => session.click());
    expect(openSession).toHaveBeenCalledWith("worker-session");
    expect(container.textContent).toContain("操作工具中");
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
    expect(container.textContent).toContain("会话 1");
    expect(container.textContent).toContain("智能体 1");
    const session = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("会话 1"))!;
    await act(async () => session.click());
    expect(openSession).toHaveBeenCalledWith("worker-session");
  });
});
