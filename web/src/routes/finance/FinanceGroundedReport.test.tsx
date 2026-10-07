// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchFinancialReportText } from "../../api/financialReports";
import { FinanceGroundedReportBody } from "./FinanceGroundedReport";

vi.mock("../../api/financialReports", () => ({ fetchFinancialReportText: vi.fn() }));
vi.mock("../../components/conversation/LazyConversationMarkdownRenderer", () => ({ LazyConversationMarkdownRenderer: ({ content }: { content: string }) => <div data-markdown>{content}</div> }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe("grounded financial report reads", () => {
  let root: Root, container: HTMLDivElement;
  const target = { assistantAgentId: "owner", sessionId: "session", turnId: "turn" };
  const raw = "## 结论\n利润999亿元。";
  beforeEach(() => {
    vi.mocked(fetchFinancialReportText).mockReset();
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); });
  async function render(next = target, originalText = raw) {
    await act(async () => root.render(<FinanceGroundedReportBody target={next} originalText={originalText} zh />));
  }

  it("hides the original while loading, then shows only the grounded answer and a missing-evidence notice", async () => {
    let resolve!: (text: string) => void;
    vi.mocked(fetchFinancialReportText).mockReturnValue(new Promise((done) => { resolve = done; }));
    await render();
    expect(container.textContent).toContain("读取核验正文");
    expect(container.textContent).not.toContain("999亿元");
    await act(async () => resolve("## 结论\n利润没有这一项。"));
    expect(container.querySelector("[data-markdown]")?.textContent).toBe("## 结论\n利润没有这一项。");
    expect(container.textContent).toContain("结论金额缺少证据");
  });

  it("aborts the previous exact Turn and refuses its late answer when the selected run changes", async () => {
    let resolveOld!: (text: string) => void;
    vi.mocked(fetchFinancialReportText).mockReturnValueOnce(new Promise((done) => { resolveOld = done; }));
    await render();
    const oldSignal = vi.mocked(fetchFinancialReportText).mock.calls[0][1]!.signal!;
    vi.mocked(fetchFinancialReportText).mockResolvedValueOnce("新轮次正文");
    await render({ ...target, turnId: "next-turn" });
    await act(async () => resolveOld("旧轮次私有正文"));
    expect(oldSignal.aborted).toBe(true);
    expect(container.textContent).toContain("新轮次正文");
    expect(container.textContent).not.toContain("旧轮次");
  });

  it("keeps an unavailable report retryable without falling back to ungrounded content", async () => {
    vi.mocked(fetchFinancialReportText).mockRejectedValueOnce(new Error("权限或网络异常"));
    await render();
    expect(container.textContent).toContain("报告读取失败");
    expect(container.textContent).not.toContain("999亿元");
    vi.mocked(fetchFinancialReportText).mockResolvedValueOnce("重试后的精确正文");
    await act(async () => container.querySelector("button")!.click());
    expect(container.textContent).toContain("重试后的精确正文");
    expect(fetchFinancialReportText).toHaveBeenCalledTimes(2);
  });

  it("does not claim an evidence failure for an existing mention of the missing-data phrase", async () => {
    const discussion = "缺少信息时写没有这一项，不要编造。";
    vi.mocked(fetchFinancialReportText).mockResolvedValue(discussion);
    await render(target, discussion);
    expect(container.querySelector("[data-markdown]")?.textContent).toBe(discussion);
    expect(container.textContent).not.toContain("结论金额缺少证据");
  });
});
