// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FinanceKnowledgeCenter } from "./FinanceKnowledgeCenter";
import type { FinancialAssistant } from "../../api/financialAssistant";

const api = vi.hoisted(() => ({ memory: vi.fn(), preferences: vi.fn(), save: vi.fn(), remove: vi.fn(), skills: vi.fn(), detail: vi.fn() }));
vi.mock("../../api/memory", () => ({ fetchMemoryAgentDetail: api.memory }));
vi.mock("../../api/financialPreferences", () => ({ fetchFinancialPreferences: api.preferences, saveFinancialPreference: api.save, removeFinancialPreference: api.remove, financialPreferenceKeys: { agent: (id: string) => ["finance", "preferences", id] } }));
vi.mock("../../api/skills", () => ({ fetchSkillLibrary: api.skills, fetchSkillLibraryDetail: api.detail }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const assistant = { agentId: "finance-owner" } as FinancialAssistant;
const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const draft = vi.fn();
let root: Root, client: QueryClient, container: HTMLDivElement;
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 10))); }
async function render(mode: "memory" | "skills" | "learning") {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceKnowledgeCenter assistant={assistant} stock={stock} zh mode={mode} onResearchPrompt={draft} /></QueryClientProvider>));
  await settle();
}
function button(text: string) { return [...container.querySelectorAll("button")].find((node) => node.textContent?.includes(text))!; }
beforeEach(() => {
  vi.resetAllMocks();
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  api.memory.mockResolvedValue({ selectedAgent: { agentId: assistant.agentId, items: [] } });
  api.preferences.mockResolvedValue({ agentId: assistant.agentId, memoryEnabled: true, items: [], limit: 200 });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); });

describe("Finance knowledge center", () => {
  it("reads only the same Agent and saves preferences once after an explicit click", async () => {
    let resolve!: (value: unknown) => void;
    api.save.mockImplementation(() => new Promise((done) => { resolve = done; }));
    await render("memory");
    expect(api.memory).toHaveBeenCalledWith(assistant.agentId, expect.objectContaining({ actorAgentId: assistant.agentId, includeContent: true }));
    expect(api.save).not.toHaveBeenCalled(); expect(draft).not.toHaveBeenCalled();
    const input = container.querySelector("textarea")!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, "现金流优先"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => { button("保存偏好").click(); button("保存偏好").click(); });
    expect(api.save).toHaveBeenCalledTimes(1);
    expect(api.save).toHaveBeenCalledWith(assistant.agentId, "现金流优先", expect.stringMatching(/^[\da-f-]{36}$/));
    api.preferences.mockResolvedValue({ agentId: assistant.agentId, memoryEnabled: true, items: [{ id: "preference-1", text: "现金流优先", createdAt: "" }], limit: 200 });
    await act(async () => resolve({ id: "preference-1" })); await settle();
    expect(container.textContent).toContain("已保存偏好"); expect(container.textContent).toContain("现金流优先");
    expect(container.textContent).not.toContain("暂无已保存记忆");
    expect(draft).not.toHaveBeenCalled();
  });
  it("keeps unavailable or disabled memory visible without claiming a write", async () => {
    api.preferences.mockResolvedValue({ agentId: assistant.agentId, memoryEnabled: false, items: [], limit: 200 });
    await render("memory");
    expect(container.textContent).toContain("个人记忆已关闭");
    expect(button("保存偏好").disabled).toBe(true);
    expect(api.save).not.toHaveBeenCalled();
  });
  it("uses the actual native slash command after previewing the selected skill", async () => {
    const skill = { name: "Evidence review", command: "/evidence-review", description: "核对原始证据", source: "agents", content: "Skill source body", hash: "hash-one" };
    api.skills.mockResolvedValue({ skills: [skill] }); api.detail.mockResolvedValue(skill);
    await render("skills");
    await act(async () => button("Evidence review").click()); await settle();
    expect(api.detail).toHaveBeenCalledWith("evidence-review");
    expect(container.textContent).toContain(skill.content);
    expect(draft).not.toHaveBeenCalled();
    await act(async () => button("用此技能研究").click());
    expect(draft).toHaveBeenCalledWith(expect.stringMatching(/^\/evidence-review\n/));
    expect(draft.mock.calls[0][0]).toContain(stock.ticker);
  });
  it("lists a native executable skill command once across mirrored sources", async () => {
    const skill = { name: "Evidence review", command: "/evidence-review", description: "核对原始证据", source: "agents", content: "Native selected source body" };
    api.skills.mockResolvedValue({ skills: [skill, { ...skill, source: "codex" }] }); api.detail.mockResolvedValue(skill);
    await render("skills");
    expect([...container.querySelectorAll("button")].filter((node) => node.textContent?.includes(skill.name))).toHaveLength(1);
    await act(async () => button(skill.name).click()); await settle();
    expect(api.detail).toHaveBeenCalledWith("evidence-review");
    expect(container.textContent).toContain(skill.content);
  });
  it("offers five lessons and resets the quiz before starting a real research exercise", async () => {
    await render("learning");
    expect(button("5. 模拟交易")).toBeTruthy(); expect(button("核对一份年报")).toBeTruthy();
    await act(async () => button("公司年报披露的营业收入").click());
    expect(container.textContent).toContain("回答正确");
    await act(async () => button("2. 读懂盈利").click());
    expect(container.querySelector('[role="status"]')).toBeNull();
    await act(async () => button("用当前股票练习").click());
    expect(draft).toHaveBeenCalledWith(expect.stringContaining(stock.ticker));
  });
});
