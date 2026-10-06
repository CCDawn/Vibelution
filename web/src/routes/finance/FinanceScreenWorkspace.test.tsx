// @vitest-environment happy-dom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StockIdentity } from "../../api/financialMarket";
import { FinanceScreenWorkspace } from "./FinanceScreenWorkspace";

const explorer = vi.hoisted(() => ({ props: [] as Array<Record<string, unknown>> }));
vi.mock("./FinanceMarketExplorer", () => ({
  FinanceMarketExplorer: (props: Record<string, unknown>) => {
    explorer.props.push(props);
    return <div data-testid="advanced-screen">{String(props.agentId)}</div>;
  },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const stock: StockIdentity = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
let root: Root | null = null;
let node: HTMLDivElement;

async function render(props: Partial<React.ComponentProps<typeof FinanceScreenWorkspace>> = {}) {
  await act(async () => root?.render(<FinanceScreenWorkspace
    agentId="finance-agent-1"
    currentStock={stock}
    onResearchPrompt={() => {}}
    onSelectStock={() => {}}
    zh
    {...props}
  />));
}

function buttonWithText(text: string): HTMLButtonElement {
  const button = Array.from(node.querySelectorAll("button")).find((item) => item.textContent?.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}

async function tabWithText(text: string) {
  const tab = Array.from(node.querySelectorAll<HTMLElement>('[role="tab"]')).find((item) => item.textContent?.includes(text));
  if (!tab) throw new Error(`Tab not found: ${text}`);
  await act(async () => tab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
}

function setTextarea(label: string, value: string) {
  const field = node.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${label}"]`);
  if (!field) throw new Error(`Textarea not found: ${label}`);
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  explorer.props = [];
  node = document.createElement("div");
  document.body.appendChild(node);
  root = createRoot(node);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  node.remove();
});

describe("FinanceScreenWorkspace", () => {
  it("starts with natural-language screening and sends a grounded native prompt", async () => {
    const onResearchPrompt = vi.fn();
    await render({ onResearchPrompt });
    expect(node.textContent).toContain("智能选股");
    expect(node.textContent).toContain("高级筛选");
    expect(node.textContent).toContain("涨幅超过3%，成交额高于5亿元");
    expect(buttonWithText("开始选股").disabled).toBe(true);

    await act(async () => buttonWithText("涨幅超过3%").click());
    expect(buttonWithText("开始选股").disabled).toBe(false);
    await act(async () => buttonWithText("开始选股").click());
    expect(onResearchPrompt).toHaveBeenCalledTimes(1);
    expect(onResearchPrompt).toHaveBeenCalledWith(expect.stringContaining("用户选股条件：涨幅超过3%，成交额高于5亿元"));
    expect(onResearchPrompt).toHaveBeenCalledWith(expect.stringMatching(/^请研究以下股票筛选条件，生成筛选报告。分析截至 \d{4}-\d{2}-\d{2}/));
    expect(onResearchPrompt).toHaveBeenCalledWith(expect.stringContaining("financial_market_screen_tool"));
    expect(onResearchPrompt).toHaveBeenCalledWith(expect.stringContaining("已加载数量/行情池总数"));
    expect(onResearchPrompt).toHaveBeenCalledWith(expect.stringContaining("不得虚构或补齐股票数据"));
    expect(explorer.props).toHaveLength(0);
  });

  it("hands the selected Agent and stock to the advanced screener", async () => {
    await render();
    await tabWithText("高级筛选");
    expect(node.querySelector('[data-testid="advanced-screen"]')).not.toBeNull();
    expect(explorer.props).toHaveLength(1);
    expect(explorer.props[0]).toEqual(expect.objectContaining({
      agentId: "finance-agent-1",
      mode: "screen",
      stock,
      researchDisabled: false,
      zh: true,
    }));
  });

  it("passes the native research disabled state to the advanced screener", async () => {
    await render({ disabled: true });
    await tabWithText("高级筛选");
    expect(explorer.props[0]).toEqual(expect.objectContaining({ researchDisabled: true }));
  });

  it("keeps screening criteria and examples unavailable when the native handoff is disabled", async () => {
    await render({ disabled: true });
    expect(buttonWithText("PE低于20").disabled).toBe(true);
    expect(buttonWithText("开始选股").disabled).toBe(true);
    expect(node.querySelector<HTMLTextAreaElement>("textarea[aria-label='选股条件']")?.disabled).toBe(true);
  });
});
