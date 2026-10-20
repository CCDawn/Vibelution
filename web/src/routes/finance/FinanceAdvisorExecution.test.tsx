// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { FinancialManualPosition } from "../../api/types/financialPreferences";
import { FinanceAdvisorExecution } from "./FinanceAdvisorExecution";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
const initialPosition: FinancialManualPosition = {
  id: "position-1",
  stock: { symbol: "sh600000", ticker: "600000", name: "浦发银行", market: "上交所", marketCode: "CN", currency: "CNY", marketTimeZone: "Asia/Shanghai" },
  quantity: 100,
  costPrice: 10,
  currency: "CNY",
  note: "原备注",
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function render(options: Partial<{
  initialPositions: FinancialManualPosition[];
  initialCash: number | null;
  pending: boolean;
  onConfirm: (cash: number, positions: FinancialManualPosition[]) => Promise<void>;
}> = {}) {
  const onConfirm = options.onConfirm ?? vi.fn().mockResolvedValue(undefined);
  await act(async () => root.render(<FinanceAdvisorExecution
    initialPositions={options.initialPositions ?? []}
    initialCash={options.initialCash === undefined ? 5000 : options.initialCash}
    pending={options.pending ?? false}
    zh
    onConfirm={onConfirm}
  />));
  return onConfirm;
}

async function input(label: string, value: string) {
  const field = host.querySelector<HTMLInputElement>('input[aria-label="' + label + '"]');
  expect(field).not.toBeNull();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field!.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function confirmSnapshot() {
  await act(async () => {
    host.querySelector<HTMLButtonElement>('button[type="submit"]')!.click();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

async function confirmCompleteList() {
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
}

it("requires explicit confirmation before submitting an empty, zero-cash snapshot", async () => {
  const onConfirm = await render({ initialCash: 5000 });
  expect(host.querySelector<HTMLInputElement>('input[aria-label="实际可用现金（元）"]')?.value).toBe("");
  expect(host.textContent).toContain("我确认当前没有任何持仓");
  await input("实际可用现金（元）", "0");
  await confirmSnapshot();
  expect(onConfirm).not.toHaveBeenCalled();
  expect(host.textContent).toContain("请先确认");

  await confirmCompleteList();
  await confirmSnapshot();
  expect(onConfirm).toHaveBeenCalledWith(0, []);
});

it("sends only the reviewed holding snapshot and preserves an old identity until its code changes", async () => {
  const onConfirm = await render({ initialPositions: [initialPosition], initialCash: 2500 });
  expect(host.querySelector<HTMLInputElement>('input[aria-label="实际可用现金（元）"]')?.value).toBe("");
  expect(host.textContent).toContain("浦发银行");
  await input("实际可用现金（元）", "0");
  await input("持仓 1 股票代码", "sz000001");
  await input("持仓 1 持有数量（股）", "200");
  await input("持仓 1 持仓成本（元/股）", "12.5");
  await confirmCompleteList();
  await confirmSnapshot();

  expect(onConfirm).toHaveBeenCalledWith(0, [{
    id: "position-1",
    stock: { symbol: "sz000001", ticker: "000001", name: "000001", market: "深交所" },
    quantity: 200,
    costPrice: 12.5,
    currency: "CNY",
    note: "",
  }]);
});

it("preserves the baseline stock identity and note when the code remains unchanged", async () => {
  const onConfirm = await render({ initialPositions: [initialPosition], initialCash: null });
  await input("实际可用现金（元）", "300");
  await input("持仓 1 持有数量（股）", "150");
  await confirmCompleteList();
  await confirmSnapshot();

  expect(onConfirm).toHaveBeenCalledWith(300, [{
    id: "position-1",
    stock: { symbol: "sh600000", ticker: "600000", name: "浦发银行", market: "上交所" },
    quantity: 150,
    costPrice: 10,
    currency: "CNY",
    note: "原备注",
  }]);
});

it("rejects non-canonical A-share codes and fractional share quantities", async () => {
  const onConfirm = await render({ initialPositions: [initialPosition] });
  await input("实际可用现金（元）", "100");
  await input("持仓 1 股票代码", "sh300000");
  await confirmCompleteList();
  await confirmSnapshot();

  expect(onConfirm).not.toHaveBeenCalled();
  expect(host.textContent).toContain("股票代码无效");

  await input("持仓 1 股票代码", "sh600001");
  await input("持仓 1 持有数量（股）", "1.5");
  await confirmCompleteList();
  await confirmSnapshot();
  expect(onConfirm).not.toHaveBeenCalled();
  expect(host.textContent).toContain("持仓数量必须是大于 0 的整数");
});

it("rejects duplicate symbols in the complete snapshot", async () => {
  const onConfirm = await render({ initialPositions: [initialPosition, { ...initialPosition, id: "position-2" }] });
  await input("实际可用现金（元）", "100");
  await confirmCompleteList();
  await confirmSnapshot();

  expect(onConfirm).not.toHaveBeenCalled();
  expect(host.textContent).toContain("股票代码 sh600000 重复");
});

it("keeps the reviewed edits visible when onConfirm fails", async () => {
  const onConfirm = vi.fn().mockRejectedValue(new Error("离线"));
  await render({ initialPositions: [initialPosition], onConfirm });
  await input("实际可用现金（元）", "1200");
  await input("持仓 1 持有数量（股）", "250");
  await input("持仓 1 持仓成本（元/股）", "11.25");
  await confirmCompleteList();
  await confirmSnapshot();

  expect(host.textContent).toContain("离线");
  expect(host.querySelector<HTMLInputElement>('input[aria-label="实际可用现金（元）"]')?.value).toBe("1200");
  expect(host.querySelector<HTMLInputElement>('input[aria-label="持仓 1 持有数量（股）"]')?.value).toBe("250");
  expect(host.querySelector<HTMLInputElement>('input[aria-label="持仓 1 持仓成本（元/股）"]')?.value).toBe("11.25");
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
  expect(host.textContent).not.toContain("已确认并提交");
});

it("disables all editing and snapshot actions while pending", async () => {
  await render({ initialPositions: [initialPosition], pending: true });
  expect([...host.querySelectorAll<HTMLInputElement>("input")].every(field => field.disabled)).toBe(true);
  expect([...host.querySelectorAll<HTMLButtonElement>("button")].every(button => button.disabled)).toBe(true);
});

it("caps the editor at 50 holdings", async () => {
  const initialPositions = Array.from({ length: 50 }, (_, index) => ({ ...initialPosition, id: "position-" + index }));
  await render({ initialPositions });

  expect(host.textContent).toContain("50/50 条");
  expect([...host.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "添加持仓")?.disabled).toBe(true);
});
