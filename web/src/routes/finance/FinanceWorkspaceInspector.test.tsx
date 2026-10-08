// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinanceWorkspaceInspector } from "./FinanceWorkspaceInspector";
import type { ReportCitation } from "./stockResearchModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
afterEach(() => { act(() => root?.unmount()); root = undefined; document.body.replaceChildren(); });
const props = { area: "workspace", title: "股票研究", stock: { symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所" }, report: null, selection: null, preparing: false, date: "2026-10-07", zh: true };

describe("FinanceWorkspaceInspector report sources", () => {
  it("opens the exact citation and replaces old references when the report changes", async () => {
    const open = vi.fn();
    const first: ReportCitation = { label: "年度报告", page: "12", url: "https://example.com/annual.pdf" };
    const next: ReportCitation = { label: "中期报告", page: "30", url: "https://example.com/interim.pdf" };
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root?.render(<FinanceWorkspaceInspector {...props} reportCitations={[first]} onCitation={open} />));
    expect(container.querySelector('[aria-label="报告引用"]')?.textContent).toContain("年度报告 · 第12页");
    await act(async () => container.querySelector<HTMLButtonElement>("button")!.click());
    expect(open).toHaveBeenLastCalledWith(first);
    await act(async () => root?.render(<FinanceWorkspaceInspector {...props} topicTitle="主题研究" reportCitations={[next]} onCitation={open} />));
    expect(container.textContent).not.toContain("年度报告");
    expect(container.querySelector('[aria-label="当前股票"]')).toBeNull();
    await act(async () => container.querySelector<HTMLButtonElement>("button")!.click());
    expect(open).toHaveBeenLastCalledWith(next);
  });

  it("shows missing references only for an explicitly supplied report", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root?.render(<FinanceWorkspaceInspector {...props} onCitation={() => {}} />));
    expect(container.querySelector('[aria-label="报告引用"]')).toBeNull();
    await act(async () => root?.render(<FinanceWorkspaceInspector {...props} reportCitations={[]} onCitation={() => {}} />));
    expect(container.textContent).toContain("报告未列出引用");
  });
});
