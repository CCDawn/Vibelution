// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FinanceGeneralResearch, generalResearchPrompt } from "./FinanceGeneralResearch";
import { localResearchDate, RESEARCH_DEPTH_INSTRUCTIONS, type ResearchDepth } from "./stockResearchModel";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root, container: HTMLDivElement;
const start = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render(disabled = false) {
  await act(async () => root.render(<FinanceGeneralResearch zh disabled={disabled} pending={false} onStart={start} />));
}
async function changeDate(value: string) {
  const input = container.querySelector<HTMLInputElement>('input[type="date"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
function button(label: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent === label)!; }

describe("Finance topic research", () => {
  it("prepares the selected example with the current date and standard depth only after clicking start", async () => {
    await render();
    expect(container.querySelector("h1")?.textContent).toBe("主题研究");
    expect(button("开始主题研究").disabled).toBe(true);
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent?.includes("降息对银行"))!.click());
    expect(start).not.toHaveBeenCalled();
    await act(async () => button("开始主题研究").click());
    expect(start).toHaveBeenCalledWith(generalResearchPrompt("降息对银行、地产和消费行业的影响", localResearchDate(), "standard"), "降息对银行、地产和消费行业的影响", "standard");
  });
  it("retains the future-date and disabled gates", async () => {
    await render();
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent?.includes("降息对银行"))!.click());
    await changeDate("2999-01-01");
    expect(button("开始主题研究").disabled).toBe(true);
    expect(container.querySelector('input[type="date"]')?.getAttribute("aria-invalid")).toBe("true");
    await changeDate(localResearchDate());
    expect(button("开始主题研究").disabled).toBe(false);
    await render(true);
    expect(button("开始主题研究").disabled).toBe(true);
    expect(start).not.toHaveBeenCalled();
  });
  it.each(Object.keys(RESEARCH_DEPTH_INSTRUCTIONS) as ResearchDepth[])("keeps the %s depth instructions in the research prompt", depth => {
    expect(generalResearchPrompt("  主题  ", "2026-01-01", depth)).toContain(RESEARCH_DEPTH_INSTRUCTIONS[depth]);
    expect(generalResearchPrompt("  主题  ", "2026-01-01", depth)).toContain("主题。分析截至 2026-01-01");
  });
});
