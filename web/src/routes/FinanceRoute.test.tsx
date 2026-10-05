// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../api/financialAssistant";
import { FinanceRoute } from "./FinanceRoute";
import { FinancialAssistantChatNote } from "./finance/FinancialAssistantChatNote";
import { fetchSessionDetail, createChatSession, querySessions } from "../api/chat";
import { listKnowledgeItems } from "../api/knowledge";
import { useFinancialResearchSessionBridge } from "./finance/FinancialResearchBridge";
import type { SessionDetail, SessionQueryResponse } from "../api/types";
import { fetchFinancialStock, searchFinancialStocks } from "../api/financialMarket";
import { unarchiveChatSession } from "../api/sessionArchive";

const nativeSubmit = vi.fn();
let nativeMessages: SessionDetail["messages"] = [];

vi.mock("../api/financialAssistant", () => ({ createFinancialAssistant: vi.fn(), listFinancialAssistants: vi.fn() }));
vi.mock("../api/chat", () => ({ fetchSessionDetail: vi.fn(), createChatSession: vi.fn(), querySessions: vi.fn() }));
vi.mock("../api/financialMarket", async (original) => ({ ...await original<typeof import("../api/financialMarket")>(), fetchFinancialStock: vi.fn(), searchFinancialStocks: vi.fn() }));
vi.mock("../api/knowledge", () => ({ listKnowledgeItems: vi.fn(), fetchKnowledgeTrace: vi.fn() }));
vi.mock("../api/sessionArchive", () => ({ unarchiveChatSession: vi.fn(), archiveChatSession: vi.fn(), listArchivedChatSessions: vi.fn() }));
vi.mock("../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
vi.mock("./finance/FinancePortfolioResearch", () => ({ FinancePortfolioResearch: ({ onResearchPrompt }: { onResearchPrompt: (text: string) => void }) => <button onClick={() => onResearchPrompt("请对以下模拟持仓做组合诊断。")}>生成组合诊断草稿</button> }));
vi.mock("./ChatCodingRoute", () => ({ ChatCodingRoute: () => {
  const id = new URLSearchParams(useLocation().search).get("session") || "";
  const [draft, setDraft] = React.useState("");
  useFinancialResearchSessionBridge({
    sessionId: id, agentId: "finance-a", title: "原生研究", status: "idle", busy: false, stopping: false,
    messages: nativeMessages,
    onComposerChange: setDraft, onFocusComposer: () => {},
    composerValue: draft, onSubmit: () => nativeSubmit(draft),
  });
  return <div>finance-workspace<textarea aria-label="native draft" value={draft} onChange={(event) => setDraft(event.target.value)} /></div>;
} }));
vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement; let root: Root; let client: QueryClient;
const row: FinancialAssistant = {
  agentId: "finance-a", agentCode: "A001", displayName: "炒股智能体", status: "active",
  setupStatus: "ready", directSessionId: "native-session", knowledgeBaseId: "agent:finance-a:reports",
  knowledgeReadable: true, modelStatus: "configured_unverified", reportStatus: "not_configured",
  newsDelegationStatus: "disabled", marketDataStatus: "not_connected", privateLedgerStatus: "not_implemented",
  tradingEnabled: false,
};
function LocationEcho() {
  const location = useLocation();
  return <output>{location.pathname}{location.search}</output>;
}
beforeEach(() => {
  vi.resetAllMocks();
  nativeMessages = [];
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  vi.mocked(listFinancialAssistants).mockResolvedValue([row]);
  vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [] });
  vi.mocked(fetchSessionDetail).mockImplementation(async (id) => nativeSession(id));
  vi.mocked(querySessions).mockResolvedValue({ items: [nativeSession("native-session"), { ...nativeSession("history-session"), title: "年度研究" }], nextCursor: "" } as SessionQueryResponse);
  vi.mocked(createChatSession).mockResolvedValue(nativeSession("new-session"));
  vi.mocked(fetchFinancialStock).mockRejectedValue(new Error("行情暂不可用"));
  vi.mocked(searchFinancialStocks).mockResolvedValue([{ symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" }]);
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.clearAllMocks(); });
async function render(path = "/finance") {
  await act(async () => root.render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <LocationEcho />
        <Routes><Route path="/finance" element={<FinanceRoute />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  ));
  await settle();
  await settle();
}
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 20))); }
function button(label: string) { return [...container.querySelectorAll("button")].find((item) => item.textContent?.includes(label)); }
function nativeSession(id: string): SessionDetail {
  return { id, agentId: "finance-a", title: "原生研究", status: "idle", taskSummary: "", lastActive: "", updatedAt: "", currentPhase: "", messages: [], defaultFileContext: "", previewTabs: [], activePreviewPath: "", changedFiles: [], readFiles: [] };
}
async function input(label: string, value: string) {
  const field = container.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("financial assistant page", () => {
  it("reopens an empty direct binding on the same assistant after native deletion", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ ...row, setupStatus: "session_missing", directSessionId: "" }]);
    vi.mocked(createFinancialAssistant).mockResolvedValue({ created: false, assistant: row });
    await render();
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=native-session");
    expect(container.textContent).toContain("finance-workspace");
  });
  it("offers native recovery for an archived direct session while keeping the assistant active", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValueOnce([{ ...row, directSessionArchived: true }]).mockResolvedValue([{ ...row, directSessionArchived: false }]);
    vi.mocked(unarchiveChatSession).mockResolvedValue({ sessionId: row.directSessionId, status: "active", changed: true });
    await render("/finance?session=native-session");
    expect(container.textContent).toContain("这条研究已归档");
    expect(container.textContent).not.toContain("金融助手已归档");
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    await act(async () => { button("恢复研究")!.click(); button("恢复研究")!.click(); });
    expect(unarchiveChatSession).toHaveBeenCalledTimes(1);
    expect(createChatSession).not.toHaveBeenCalled();
    await settle();
    expect(container.textContent).toContain("finance-workspace");
  });
  it("starts a topic in its own native session without sending duplicate turns", async () => {
    await render("/finance?session=native-session");
    await act(async () => button("通用研究")!.click());
    const field = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="研究主题"]')!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(field, "人工智能算力产业链"); field.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => { button("开始研究")!.click(); button("开始研究")!.click(); }); await settle();
    expect(createChatSession).toHaveBeenCalledTimes(1);
    expect(createChatSession).toHaveBeenCalledWith({ agentId: row.agentId, title: "主题 · 人工智能算力产业链" }, expect.any(String));
    expect(nativeSubmit).toHaveBeenCalledTimes(1);
    expect(nativeSubmit.mock.calls[0][0]).toContain("人工智能算力产业链");
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=new-session");
  });
  it("prepares portfolio research in a separate topic session without auto-submission", async () => {
    await render("/finance?session=native-session");
    await act(async () => button("组合研究")!.click());
    await act(async () => { button("生成组合诊断草稿")!.click(); button("生成组合诊断草稿")!.click(); }); await settle();
    expect(createChatSession).toHaveBeenCalledTimes(1);
    expect(createChatSession).toHaveBeenCalledWith({ agentId: row.agentId, title: "主题 · 模拟持仓研究" }, expect.any(String));
    expect(container.querySelector<HTMLTextAreaElement>('textarea[aria-label="native draft"]')?.value).toBe("请对以下模拟持仓做组合诊断。");
    expect(nativeSubmit).not.toHaveBeenCalled();
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=new-session");
  });
  it("keeps reads pure and upgrades market queries only on an explicit single click", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ ...row, marketToolStatus: "upgrade_available" }]);
    let resolve!: (value: { created: boolean; assistant: FinancialAssistant }) => void;
    vi.mocked(createFinancialAssistant).mockReturnValue(new Promise((done) => { resolve = done; }));
    await render("/finance?session=native-session");
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    const enable = button("启用行情查询")!;
    expect(enable).toBeTruthy();
    await act(async () => { enable.click(); enable.click(); });
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    expect(button("启用行情查询")?.disabled).toBe(true);
    await act(async () => resolve({ created: false, assistant: { ...row, marketToolStatus: "assigned" } }));
    await settle();
    expect(button("启用行情查询")).toBeUndefined();
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=native-session");
    expect(createChatSession).not.toHaveBeenCalled();
  });

  it("keeps a failed market activation retryable without sending research", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ ...row, marketToolStatus: "upgrade_available" }]);
    vi.mocked(createFinancialAssistant).mockRejectedValue(new Error("启用未完成"));
    await render("/finance?session=native-session");
    await act(async () => button("启用行情查询")!.click());
    await settle();
    expect(container.textContent).toContain("启用未完成");
    expect(button("启用行情查询")?.disabled).toBe(false);
    expect(nativeSubmit).not.toHaveBeenCalled();
  });

  it("opens the assistant workspace on its own page", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([row]);
    await render();
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=native-session");
    expect(container.textContent).toContain("finance-workspace");
    expect(container.textContent).not.toContain("Conversation Agents");
    await act(async () => root.render(
      <QueryClientProvider client={client}><MemoryRouter initialEntries={["/finance?session=native-session"]}>
        <FinancialAssistantChatNote sessionId="native-session" lang="zh" />
      </MemoryRouter></QueryClientProvider>,
    ));
    await settle();
    expect(listFinancialAssistants).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("不会自动下单");
  });

  it("creates the assistant once, then stays on this page", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([]);
    vi.mocked(createFinancialAssistant).mockResolvedValue({ created: true, assistant: row });
    await render();
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=native-session");
    expect(container.textContent).toContain("finance-workspace");
    await act(async () => root.render(
      <QueryClientProvider client={client}><MemoryRouter initialEntries={["/finance?session=native-session"]}>
        <FinancialAssistantChatNote sessionId="native-session" lang="zh" />
      </MemoryRouter></QueryClientProvider>,
    ));
    await settle();
    expect(listFinancialAssistants).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("不会自动下单");
  });

  it("verifies the financial identity on a direct deep link without creating another assistant", async () => {
    await render("/finance?session=native-session");
    expect(listFinancialAssistants).toHaveBeenCalledTimes(1);
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(fetchSessionDetail).not.toHaveBeenCalled();
    expect(container.textContent).toContain("finance-workspace");
    const sourceTab = [...container.querySelectorAll('[role="tab"]')].find((tab) => tab.textContent === "引用与资料");
    await act(async () => sourceTab?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await settle();
    expect(listKnowledgeItems).toHaveBeenCalledWith(row.knowledgeBaseId, expect.objectContaining({ agentId: row.agentId, signal: expect.any(AbortSignal) }));
  });

  it("does not leave this page after it unmounts", async () => {
    let resolve!: (value: FinancialAssistant[]) => void;
    vi.mocked(listFinancialAssistants).mockReturnValue(new Promise((done) => { resolve = done; }));
    await render();
    const signal = vi.mocked(listFinancialAssistants).mock.calls[0][0]!.signal!;
    await act(async () => root.render(<div>another route</div>));
    expect(signal.aborted).toBe(true);
    await act(async () => resolve([row]));
    await settle();
    expect(container.textContent).toBe("another route");
  });

  it("stops on an archived assistant instead of creating another", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ ...row, status: "archived", directSessionId: "", setupStatus: "ready" }]);
    await render();
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(container.textContent).toContain("已归档");
    expect(container.querySelector('[data-vui="skeleton"]')).toBeNull();
    expect(container.textContent).not.toContain("finance-workspace");
  });

  it("retries a failed open into the workspace", async () => {
    vi.mocked(listFinancialAssistants).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([row]);
    await render();
    expect(container.textContent).toContain("助手加载失败");
    await act(async () => button("重试")!.click());
    await settle();
    expect(container.textContent).toContain("finance-workspace");
  });

  it("does not create twice when effects replay during entry", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([]);
    vi.mocked(createFinancialAssistant).mockResolvedValue({ created: true, assistant: row });
    await act(async () => root.render(
      <React.StrictMode><QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/finance"]}>
          <Routes><Route path="/finance" element={<FinanceRoute />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider></React.StrictMode>,
    ));
    await settle();
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("finance-workspace");
  });

  it("keeps the loading and ready states in the same financial workspace recipe", async () => {
    let resolve!: (value: FinancialAssistant[]) => void;
    vi.mocked(listFinancialAssistants).mockReturnValue(new Promise((done) => { resolve = done; }));
    await render();
    expect(container.querySelector('[data-vui-domain-recipe="financial-assistant-workspace"]')).not.toBeNull();
    expect(container.querySelector('[data-finance-entry-state="loading"]')).not.toBeNull();
    expect(container.querySelector('[data-vui-domain-recipe="financial-assistant-workspace"] header')).toBeNull();
    await act(async () => resolve([row]));
    await settle();
    expect(container.querySelector('[data-vui-domain-recipe="financial-assistant-workspace"]')).not.toBeNull();
    expect(container.textContent).toContain("finance-workspace");
    expect(container.querySelector('[data-vui-domain-recipe="financial-assistant-workspace"] header')).toBeNull();
    expect(container.querySelector('[data-vui="split-sidebar"] a[aria-label="模型与助手配置"]')).not.toBeNull();
  });

  it("rejects a session belonging to an ordinary agent", async () => {
    vi.mocked(fetchSessionDetail).mockResolvedValue({ ...nativeSession("foreign"), agentId: "ordinary-agent" });
    await render("/finance?session=foreign");
    expect(container.textContent).toContain("不属于这个金融助手");
    expect(container.textContent).not.toContain("finance-workspace");
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(querySessions).not.toHaveBeenCalled();
  });

  it("starts research through the committed native composer once on a double click", async () => {
    await render("/finance?session=native-session");
    await input("报告期", "2025FY");
    const start = button("开始研究")!;
    await act(async () => { start.click(); start.click(); });
    await settle();
    expect(nativeSubmit).toHaveBeenCalledTimes(1);
    expect(nativeSubmit.mock.calls[0][0]).toContain("贵州茅台（600519，上交所）");
    expect(nativeSubmit.mock.calls[0][0]).toContain("报告期 2025FY");
    expect(createChatSession).not.toHaveBeenCalled();
  });

  it("creates and starts one new native Session when researching after an existing turn", async () => {
    nativeMessages = [{ role: "user", id: "existing", content: "核对贵州茅台（600519）", timestamp: "" }];
    await render("/finance?session=native-session");
    await input("报告期", "2024FY");
    await act(async () => { button("开始研究")!.click(); button("开始研究")!.click(); });
    await settle();
    await settle();
    expect(createChatSession).toHaveBeenCalledTimes(1);
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=new-session");
    expect(nativeSubmit).toHaveBeenCalledTimes(1);
    expect(nativeSubmit.mock.calls[0][0]).toContain("报告期 2024FY");
  });

  it("prevents future dates from creating or submitting a native research", async () => {
    await render("/finance?session=native-session");
    await input("分析日期", "2099-01-01");
    const start = button("开始研究")!;
    expect(start.disabled).toBe(true);
    expect(container.querySelector('[aria-label="分析日期"]')?.getAttribute("aria-invalid")).toBe("true");
    await act(async () => start.click());
    expect(nativeSubmit).not.toHaveBeenCalled();
    expect(createChatSession).not.toHaveBeenCalled();
  });

  it("opens real financial history and filters foreign and archived rows", async () => {
    vi.mocked(querySessions).mockResolvedValue({
      items: [nativeSession("native-session"), { ...nativeSession("history-session"), title: "年度研究" }, { ...nativeSession("foreign"), agentId: "other", title: "外部会话" }, { ...nativeSession("archived"), title: "已归档记录", archiveState: { status: "archived" } }], nextCursor: "",
    } as SessionQueryResponse);
    await render("/finance?session=native-session");
    expect(container.textContent).not.toContain("外部会话");
    expect(container.textContent).not.toContain("已归档记录");
    await act(async () => button("年度研究")!.click());
    await settle();
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=history-session");
    expect(fetchSessionDetail).toHaveBeenCalledWith("history-session", expect.objectContaining({ transcriptScope: "none", includeSecondary: false }));
  });

  it("searches all native research bodies without changing the recent-history rail", async () => {
    vi.mocked(querySessions).mockImplementation(async (params) => ({
      items: params?.q ? [{ ...nativeSession("body-match"), title: "经营质量", updatedAt: "2026-10-05T13:49:11" }, { ...nativeSession("native-session"), lastTurnStatus: "ready", terminalReason: "ready" }] : [{ ...nativeSession("recent"), title: "年度研究" }], nextCursor: "",
    } as SessionQueryResponse));
    await render("/finance?session=native-session");
    await act(async () => button("报告中心")!.click());
    await settle();
    const input = container.querySelector('input[aria-label="搜索研究记录"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "只在正文出现的关键词");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => new Promise((resolve) => setTimeout(resolve, 280)));
    await settle();
    expect(querySessions).toHaveBeenCalledWith(expect.objectContaining({ agentId: "finance-a", q: "只在正文出现的关键词" }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(input.closest('[data-finance-report-history]')?.textContent).toContain("经营质量");
    expect(input.closest('[data-finance-report-history]')?.textContent).not.toContain("原生研究");
    expect(container.textContent).toContain("年度研究");
  });

  it("creates once on a double click and does not steal selection after opening history", async () => {
    let resolve!: (value: SessionDetail) => void;
    vi.mocked(createChatSession).mockReturnValue(new Promise((done) => { resolve = done; }));
    await render("/finance?session=native-session");
    const create = button("新研究")!;
    await act(async () => { create.click(); create.click(); });
    expect(createChatSession).toHaveBeenCalledTimes(1);
    expect(createChatSession).toHaveBeenCalledWith(expect.objectContaining({ agentId: "finance-a" }), expect.any(String));
    await act(async () => button("年度研究")!.click());
    await settle();
    await act(async () => resolve(nativeSession("late-session")));
    await settle();
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=history-session");
  });

  it("keeps the idempotency key when a create result is unknown and the user retries", async () => {
    vi.mocked(createChatSession).mockRejectedValueOnce(new Error("timeout")).mockResolvedValue(nativeSession("new-session"));
    await render("/finance?session=native-session");
    await act(async () => button("新研究")!.click());
    await settle();
    expect(container.textContent).toContain("timeout");
    await act(async () => button("新研究")!.click());
    await settle();
    const calls = vi.mocked(createChatSession).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0][1]).toBe(calls[1][1]);
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=new-session");
  });

  it("does not treat a Companion link as a financial conversation", async () => {
    await render("/finance?session=native-session&companion=someone");
    expect(container.textContent).not.toContain("finance-workspace");
    expect(createFinancialAssistant).not.toHaveBeenCalled();
  });
});
