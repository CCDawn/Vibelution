// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../api/financialAssistant";
import { FinanceRoute } from "./FinanceRoute";
import { FinancialAssistantChatNote } from "./finance/FinancialAssistantChatNote";
import { deleteChatSession, fetchSessionDetail, createChatSession, querySessions } from "../api/chat";
import { listKnowledgeItems } from "../api/knowledge";
import { useFinancialResearchSessionBridge } from "./finance/FinancialResearchBridge";
import type { SessionDetail, SessionLlmModelOption, SessionModelSelection, SessionQueryResponse } from "../api/types";
import { fetchFinancialStock, searchFinancialStocks } from "../api/financialMarket";
import { listArchivedChatSessions, unarchiveChatSession } from "../api/sessionArchive";
import { fetchFinancialReportText } from "../api/financialReports";
import { fetchFinancialReflection } from "../api/financialEvaluation";

const nativeSubmit = vi.fn();
let nativeMessages: SessionDetail["messages"] = [];
let nativeTitle = "原生研究";
let modelContextWindow = 128_000;
const researchModel: SessionLlmModelOption = { modelId: "research", modelRef: "provider/research", model: "research", label: "研究模型", providerId: "provider", providerLabel: "Provider", providerKind: "openai", apiKeyConfigured: true, missingApiKey: false, supportsReasoningEffort: true, reasoningEffortValues: ["low", "medium", "high"], reasoningEffortOptions: [], defaultReasoningEffort: "medium", isDefault: true };

vi.mock("../api/financialAssistant", () => ({ createFinancialAssistant: vi.fn(), listFinancialAssistants: vi.fn() }));
vi.mock("../api/chat", () => ({ deleteChatSession: vi.fn(), fetchSessionDetail: vi.fn(), createChatSession: vi.fn(), querySessions: vi.fn() }));
vi.mock("../api/financialMarket", async (original) => ({ ...await original<typeof import("../api/financialMarket")>(), fetchFinancialStock: vi.fn(), searchFinancialStocks: vi.fn() }));
vi.mock("../api/knowledge", () => ({ listKnowledgeItems: vi.fn(), fetchKnowledgeTrace: vi.fn() }));
vi.mock("../api/financialPreferences", async (original) => ({
  ...await original<typeof import("../api/financialPreferences")>(),
  fetchFinancialWorkspace: vi.fn(async (agentId: string) => ({ schemaVersion: 1, agentId, revision: 0, updatedAt: "", selectedStock: null, watchlist: [], profiles: [], manualPositions: [], reviewCases: [] })),
  updateFinancialWorkspace: vi.fn(async (agentId: string, revision: number, patch: object) => ({ schemaVersion: 1, agentId, revision: revision + 1, updatedAt: "", selectedStock: null, watchlist: [], profiles: [], manualPositions: [], reviewCases: [], ...patch })),
}));
vi.mock("../api/financialReports", async (original) => ({ ...await original<typeof import("../api/financialReports")>(), fetchFinancialReportText: vi.fn(), fetchFinancialReports: vi.fn(async () => ({ items: [], nextCursor: "", totalEstimate: 0 })) }));
vi.mock("../api/financialEvaluation", async (original) => ({ ...await original<typeof import("../api/financialEvaluation")>(), fetchFinancialReflection: vi.fn() }));
vi.mock("./finance/FinanceDashboard", () => ({ FinanceDashboard: () => <div>市场概览</div> }));
vi.mock("./finance/FinancePaperTrading", () => ({ FinancePaperTrading: () => <div>模拟账户</div> }));
vi.mock("../api/sessionArchive", () => ({ unarchiveChatSession: vi.fn(), archiveChatSession: vi.fn(), listArchivedChatSessions: vi.fn() }));
vi.mock("../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
vi.mock("./finance/FinancePortfolioResearch", () => ({ FinancePortfolioResearch: ({ onResearchPrompt }: { onResearchPrompt: (text: string) => void }) => <button onClick={() => onResearchPrompt("请对以下模拟持仓做组合诊断。")}>生成组合诊断草稿</button> }));
vi.mock("./ChatCodingRoute", () => ({ ChatCodingRoute: () => {
  const id = new URLSearchParams(useLocation().search).get("session") || "";
  const [draft, setDraft] = React.useState("");
  const [selection, setSelection] = React.useState<SessionModelSelection | null>(null);
  const onSelectionChange = React.useCallback((_id: string, next: SessionModelSelection | null) => setSelection(next), []);
  const options = React.useMemo(() => ({ sessionId: id, currentModelId: researchModel.modelRef, currentReasoningEffort: "medium", model: { ...researchModel, contextWindow: modelContextWindow, runtimeSelectable: true, providerHealthy: true }, choices: [{ ...researchModel, contextWindow: modelContextWindow, runtimeSelectable: true, providerHealthy: true }] }), [id]);
  useFinancialResearchSessionBridge({
    sessionId: id, agentId: "finance-a", title: nativeTitle, status: "idle", busy: false, stopping: false,
    messages: nativeMessages,
    sessionLlmOptions: options, turnModelSelection: selection, onTurnModelSelectionChange: onSelectionChange,
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
  nativeTitle = "原生研究";
  modelContextWindow = 128_000;
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
  vi.mocked(fetchFinancialReflection).mockResolvedValue({ items: [] });
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
async function chooseTab(label: string) {
  const tab = [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(item => item.textContent === label)!;
  await act(async () => tab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
}
async function chooseGroup(label: string) {
  const group = [...container.querySelectorAll<HTMLButtonElement>('nav[aria-label="工作台功能分组"] button')].find(item => item.textContent === label)!;
  await act(async () => group.click());
}
async function openResearchSettings() {
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="股票资料与研究设置"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
  await act(async () => [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(item => item.textContent?.includes("股票概览与研究设置"))!.click());
}
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
  it("includes confirmed lessons in the native research request", async () => {
    vi.mocked(fetchFinancialReflection).mockResolvedValue({ items: [{ id: "lesson-a", text: "判断方向前补充可核验依据", createdAt: "2026-01-01T00:00:00Z", refs: [{ type: "item", id: "validation-a" }] }] });
    await render("/finance?session=native-session&finance_tab=overview");
    await act(async () => { button("开始研究")!.click(); });
    await settle();
    expect(nativeSubmit).toHaveBeenCalledTimes(1);
    expect(nativeSubmit.mock.calls[0][0]).toContain("判断方向前补充可核验依据");
    expect(nativeSubmit.mock.calls[0][0]).toContain("validation-a");
  });
  it("blocks stock research and offers retry when lesson context cannot be read", async () => {
    vi.mocked(fetchFinancialReflection).mockRejectedValue(new Error("context unavailable"));
    await render("/finance?session=native-session&finance_tab=overview");
    expect(container.textContent).toContain("复盘参考读取失败");
    expect(button("开始研究")?.disabled).toBe(true);
    expect(nativeSubmit).not.toHaveBeenCalled();
    vi.mocked(fetchFinancialReflection).mockResolvedValue({ items: [] });
    await act(async () => { button("重试")!.click(); });
    await settle();
    expect(button("开始研究")?.disabled).toBe(false);
  });
  it("prepares research without creating a blank session, then starts once through native submission", async () => {
    await render("/finance?session=native-session");
    const nativeDraft = container.querySelector('textarea[aria-label="native draft"]');
    await act(async () => { button("新研究")!.click(); button("新研究")!.click(); });
    await settle();
    expect(createChatSession).not.toHaveBeenCalled();
    expect(nativeSubmit).not.toHaveBeenCalled();
    expect(container.querySelector('[aria-label="公司或股票代码"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="研究设置"]')).not.toBeNull();
    expect(container.querySelector('textarea[aria-label="native draft"]')).toBe(nativeDraft);
    const query = new URLSearchParams(container.querySelector("output")!.textContent!.split("?")[1]);
    expect(query.get("session")).toBe("native-session");
    expect(query.get("finance_prepare")).toBe("1");
    await input("报告期", "2025FY");
    await act(async () => { button("开始研究")!.click(); button("开始研究")!.click(); });
    await settle(); await settle();
    expect(createChatSession).toHaveBeenCalledTimes(1);
    expect(nativeSubmit).toHaveBeenCalledTimes(1);
    expect(nativeSubmit.mock.calls[0][0]).toContain("报告期 2025FY");
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=new-session");
  });

  it("loads report deep links and replaces old research progress with current context", async () => {
    await render("/finance?session=native-session&finance_area=reports");
    expect(container.querySelector('[aria-label="研究记录范围"] [aria-selected="true"]')?.textContent).toBe("已完成报告");
    expect(container.textContent).toContain("选择报告");
    expect(button("打开研究对话")).toBeUndefined();
    await chooseGroup("行情");
    expect(container.querySelector('[aria-label="当前股票"]')?.textContent).toContain("贵州茅台");
    expect(button("打开研究对话")).toBeUndefined();
    expect(container.querySelector("output")?.textContent).toContain("finance_area=watchlist");
  });

  it("does not replace the prepared stock with a previous session's research subject on reload", async () => {
    nativeMessages = [{ role: "user", id: "existing", content: "请研究 腾讯控股（00700，港交所），分析日期 2026-10-05，重点检查财报、盈利质量与现金流。", timestamp: "" }];
    await render("/finance?session=native-session&finance_tab=overview&finance_prepare=1");
    expect(container.querySelector('[aria-label="当前股票"]')?.textContent).toContain("贵州茅台");
    expect(container.querySelector('[aria-label="当前股票"]')?.textContent).not.toContain("腾讯控股");
    expect(createChatSession).not.toHaveBeenCalled();
  });
  it("restores a topic report deep link without showing an unrelated selected stock", async () => {
    nativeTitle = "主题 · 平安银行公开行情验收";
    nativeMessages = [
      { role: "user", id: "u", timestamp: "", content: "请对以下主题开展投资研究：平安银行公开行情验收" },
      { role: "assistant", id: "a", turnId: "topic-turn", timestamp: "2026-10-07T06:40:00Z", status: "completed", turnItems: [{ type: "agent_message", phase: "final_answer", status: "completed", text: "## 结论\n报价没有这一项/股" }] },
    ] as never;
    vi.mocked(fetchFinancialReportText).mockResolvedValue("## 结论\n平安银行（sz000001）最新公开报价11.57元/股");
    await render("/finance?session=native-session&finance_tab=report");
    await settle();
    expect(container.querySelector("[data-finance-report-body]")?.textContent).toContain("11.57元/股");
    expect(container.querySelector('[aria-label="当前研究主题"]')?.textContent).toContain(nativeTitle);
    expect(container.querySelector('[aria-label="当前股票"]')).toBeNull();
    expect(createChatSession).not.toHaveBeenCalled();
    expect(nativeSubmit).not.toHaveBeenCalled();
  });
  it("opens a team summary report for its own stock instead of the last selected stock", async () => {
    nativeTitle = "股票研究汇总 · SZ000001";
    nativeMessages = [
      { role: "user", id: "u", timestamp: "", content: "你是主助手的股票研究汇总角色。请综合股票 sz000001 的多分析师研究。研究日期：2026-10-07；观察周期：近30天。\n引用资料中另有600519。" },
      { role: "assistant", id: "a", turnId: "team-turn", timestamp: "2026-10-07T06:40:00Z", status: "completed", turnItems: [{ type: "agent_message", phase: "final_answer", status: "completed", text: "## 结论\n平安银行资料不足。" }] },
    ] as never;
    vi.mocked(fetchFinancialReportText).mockResolvedValue("## 结论\n平安银行资料不足。");
    await render("/finance?session=native-session&finance_tab=report");
    await settle();
    expect(container.querySelector('[aria-label="当前股票"]')?.textContent).toContain("000001");
    expect(container.querySelector('[aria-label="当前股票"]')?.textContent).not.toContain("600519");
    expect(container.querySelector("[data-finance-report-body]")?.textContent).toContain("平安银行资料不足");
    expect(createChatSession).not.toHaveBeenCalled();
    expect(nativeSubmit).not.toHaveBeenCalled();
  });
  it("opens the native conversation first and retains all grouped workspace views", async () => {
    await render("/finance?session=native-session");
    const draft = container.querySelector('textarea[aria-label="native draft"]');
    expect(draft?.closest('[aria-hidden]')?.getAttribute("aria-hidden")).toBe("false");
    expect(container.querySelector('[aria-label="公司或股票代码"]')).toBeNull();
    expect(container.querySelector('[data-finance-session-scroll]')).not.toBeNull();
    const views = (label: string) => [...container.querySelectorAll(`[role="tablist"][aria-label="${label}功能"] [role="tab"]`)].map(tab => tab.textContent);
    expect(views("研究")).toEqual(["股票研究", "主题研究", "分析员协作", "研究任务", "总览"]);
    await chooseGroup("行情");
    expect(views("行情")).toEqual(["自选行情", "股票筛选"]);
    expect(container.querySelector('[aria-label="公司或股票代码"]')).not.toBeNull();
    await chooseGroup("资产");
    expect(views("资产")).toEqual(["模拟账户", "组合研究", "交易复盘"]);
    await chooseGroup("资料");
    expect(views("资料")).toEqual(["报告中心", "研究记忆", "技能中心", "学习中心"]);
    await chooseGroup("研究");
    expect(container.querySelector('textarea[aria-label="native draft"]')).toBe(draft);
    expect(createChatSession).not.toHaveBeenCalled();
    expect(nativeSubmit).not.toHaveBeenCalled();
  });

  it("searches native session bodies and retains the keyword for sidebar pagination", async () => {
    vi.mocked(querySessions).mockImplementation(async (params) => params?.q ? {
      items: [{ ...nativeSession(params.cursor ? "next-match" : "body-match"), title: params.cursor ? "后续记录" : "经营质量", updatedAt: "2026-10-05T13:49:11" }], nextCursor: params.cursor ? "" : "next-page",
    } as SessionQueryResponse : { items: [nativeSession("native-session")], nextCursor: "" } as SessionQueryResponse);
    await render("/finance?session=native-session");
    await input("搜索研究会话", "正文关键词");
    await act(async () => new Promise(resolve => setTimeout(resolve, 280)));
    await settle();
    const list = container.querySelector('[data-finance-session-scroll]')!;
    expect(list.textContent).toContain("经营质量");
    await act(async () => button("更多会话")!.click());
    await settle();
    expect(list.textContent).toContain("后续记录");
    expect(querySessions).toHaveBeenCalledWith(expect.objectContaining({ agentId: "finance-a", q: "正文关键词", cursor: "next-page" }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=native-session");
  });

  it("reopens an empty direct binding on the same assistant after native deletion", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ ...row, setupStatus: "session_missing", directSessionId: "" }]);
    vi.mocked(createFinancialAssistant).mockResolvedValue({ created: false, assistant: row });
    await render();
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=native-session");
    expect(container.textContent).toContain("finance-workspace");
  });
  it("keeps deletion mounted until the last direct session replacement is selected", async () => {
    await render("/finance?session=native-session");
    const repaired = { ...row, directSessionId: "replacement-direct" };
    vi.mocked(listFinancialAssistants).mockResolvedValueOnce([{ ...row, setupStatus: "session_missing", directSessionId: "" }]).mockResolvedValue([repaired]);
    vi.mocked(querySessions).mockResolvedValue({ items: [nativeSession("replacement-direct")], nextCursor: "" } as SessionQueryResponse);
    vi.mocked(deleteChatSession).mockResolvedValue({ deleted: true, deletedSessionId: "native-session", nextActiveSessionId: "foreign-agent-session" });
    let finish!: (value: Awaited<ReturnType<typeof createFinancialAssistant>>) => void;
    vi.mocked(createFinancialAssistant).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    await act(async () => container.querySelector('[aria-label="管理研究：原生研究"]')!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0, ctrlKey: false })));
    await act(async () => [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === "删除研究")!.click());
    await act(async () => [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((item) => item.textContent === "删除研究")!.click());
    await settle();
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    await act(async () => finish({ created: false, assistant: repaired }));
    await settle();
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=replacement-direct");
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
  it("blocks topic execution when the assistant model has no valid context window", async () => {
    modelContextWindow = 0;
    await render("/finance?session=native-session");
    await chooseTab("主题研究");
    expect(container.textContent).toContain("研究模型暂不可用");
    expect(button("开始研究")?.disabled).toBe(true);
    await act(async () => button("开始研究")!.click());
    expect(createChatSession).not.toHaveBeenCalled();
    expect(nativeSubmit).not.toHaveBeenCalled();
  });

  it("starts a topic in its own native session without sending duplicate turns", async () => {
    await render("/finance?session=native-session");
    await chooseTab("主题研究");
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
    await chooseGroup("资产");
    await chooseTab("组合研究");
    await act(async () => [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find((tab) => tab.textContent === "模拟持仓")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await act(async () => { button("生成组合诊断草稿")!.click(); button("生成组合诊断草稿")!.click(); }); await settle();
    expect(createChatSession).toHaveBeenCalledTimes(1);
    expect(createChatSession).toHaveBeenCalledWith({ agentId: row.agentId, title: "主题 · 模拟持仓研究" }, expect.any(String));
    const draft = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="native draft"]')?.value;
    expect(draft).toMatch(/^请对以下主题开展投资研究：模拟持仓研究/);
    expect(draft).toContain("请对以下模拟持仓做组合诊断。");
    expect(nativeSubmit).not.toHaveBeenCalled();
    const query = new URLSearchParams(container.querySelector("output")!.textContent!.split("?")[1]);
    expect(query.get("session")).toBe("new-session");
    expect(query.get("finance_area")).toBeNull();
    expect(query.get("finance_portfolioSource")).toBe("paper");
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
    expect(container.textContent).toContain("不会实盘下单");
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
    expect(container.textContent).toContain("不会实盘下单");
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
    await openResearchSettings();
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
    await openResearchSettings();
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
    await openResearchSettings();
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

  it("renders native archived research without a task summary", async () => {
    const archived = { ...nativeSession("archived-topic"), title: "已归档复盘", updatedAt: "2026-10-05T11:10:06+00:00", archiveState: { status: "archived" } };
    // The lightweight native archive projection omits taskSummary on a session
    // that has not started a Turn; the active index normally supplies it.
    delete (archived as Partial<SessionDetail>).taskSummary;
    vi.mocked(listArchivedChatSessions).mockResolvedValue({ items: [archived], nextCursor: "", totalEstimate: 1 });
    await render("/finance?session=native-session");
    await chooseGroup("资料");
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((tab) => tab.textContent === "已归档")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await settle();
    expect(listArchivedChatSessions).toHaveBeenCalledWith(expect.objectContaining({ limit: 200 }));
    expect(container.textContent).toContain("已归档复盘");
    expect(container.querySelector('[aria-label="管理研究：已归档复盘"]')).not.toBeNull();
  });

  it("searches all native research bodies without changing the recent-history rail", async () => {
    vi.mocked(querySessions).mockImplementation(async (params) => ({
      items: params?.q ? [{ ...nativeSession("body-match"), title: "经营质量", updatedAt: "2026-10-05T13:49:11" }, { ...nativeSession("native-session"), lastTurnStatus: "ready", terminalReason: "ready" }] : [{ ...nativeSession("recent"), title: "年度研究" }], nextCursor: "",
    } as SessionQueryResponse));
    await render("/finance?session=native-session");
    await chooseGroup("资料");
    await act(async () => [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find((tab) => tab.textContent === "研究会话")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
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
    await act(async () => button("新研究")!.click());
    expect(createChatSession).not.toHaveBeenCalled();
    const create = button("开始研究")!;
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
    await act(async () => button("开始研究")!.click());
    await settle();
    expect(container.textContent).toContain("timeout");
    await act(async () => button("开始研究")!.click());
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
