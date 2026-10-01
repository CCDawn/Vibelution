// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../api/financialAssistant";
import { FinanceRoute } from "./FinanceRoute";

vi.mock("../api/financialAssistant", () => ({ createFinancialAssistant: vi.fn(), listFinancialAssistants: vi.fn() }));
const { openSession } = vi.hoisted(() => ({ openSession: vi.fn() }));
vi.mock("./chat/useChatRouteSelection", () => ({ useChatRouteSelection: () => ({ openSession }) }));
vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement; let root: Root; let client: QueryClient;
const row: FinancialAssistant = { agentId: "finance-a", agentCode: "A001", displayName: "我的研究助手", status: "active", setupStatus: "ready", directSessionId: "native-session", knowledgeBaseId: "agent:finance-a:reports", knowledgeReadable: true, modelStatus: "not_configured", reportStatus: "not_configured", newsDelegationStatus: "disabled", marketDataStatus: "not_connected", privateLedgerStatus: "not_implemented", tradingEnabled: false };
beforeEach(() => { container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); });
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.clearAllMocks(); });
async function render() { await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/finance"]}><FinanceRoute /></MemoryRouter></QueryClientProvider>)); await settle(); }
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 15))); }
function button(label: string) { return [...container.querySelectorAll("button")].find((b) => b.textContent?.includes(label))!; }

describe("financial assistant entry", () => {
  it("does not auto-create on read and accurately labels missing capabilities", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([]); await render();
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(container.textContent).toContain("分钟行情和 K 线尚未接入");
    expect(container.textContent).toContain("自行判断真伪");
    expect(container.textContent).toContain("尚未接入账户、持仓和现金流账本");
    expect(button("创建").disabled).toBe(false);
  });
  it("guards repeated setup clicks and never auto-navigates on a late response", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([]);
    let resolve!: (value: { created: boolean; assistant: FinancialAssistant }) => void;
    vi.mocked(createFinancialAssistant).mockReturnValue(new Promise((r) => { resolve = r; }));
    await render(); await act(async () => button("创建").click()); await settle();
    expect(button("创建").disabled).toBe(true);
    await act(async () => button("创建").click());
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    // Leaving the route does not make a later response select a conversation.
    await act(async () => root.render(<div>another route</div>));
    await act(async () => resolve({ created: true, assistant: row })); await settle();
    expect(openSession).not.toHaveBeenCalled();
    expect(container.textContent).toBe("another route");
  });
  it("opens only a verified native session and reuses configuration and memory routes", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([row]); await render();
    await act(async () => button("进入对话").click());
    expect(openSession).toHaveBeenCalledWith("native-session", expect.objectContaining({ replace: false }));
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs.some((h) => h?.startsWith("/agents?") && h.includes("finance-a"))).toBe(true);
    expect(hrefs.some((h) => h?.includes("reports"))).toBe(true);
  });
  it("blocks archived or unverified sessions without restoring them", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ ...row, directSessionId: "", status: "archived" }]); await render();
    expect(button("进入对话").disabled).toBe(true);
    expect(button("创建")).toBeUndefined();
    expect(createFinancialAssistant).not.toHaveBeenCalled();
  });
  it("shows errors and permits bounded retry", async () => {
    vi.mocked(listFinancialAssistants).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([]); await render();
    expect(container.textContent).toContain("载入失败");
    await act(async () => button("重试").click()); await settle();
    expect(container.textContent).toContain("还没有金融助手");
  });
});
