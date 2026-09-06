/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import { ResearchRunTimeline } from "./ResearchRunTimeline";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";

vi.mock("../../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
vi.mock("./ResearchCriticalPathPanel", () => ({ ResearchCriticalPathPanel: () => <div>关键路径</div> }));
vi.mock("./ResearchWorkflowInsightsPanel", () => ({ ResearchWorkflowInsightsPanel: () => <div>科研效能</div> }));

function installPointerCaptureShims() {
  const proto = Element.prototype as unknown as Record<string, unknown>;
  if (typeof proto.hasPointerCapture !== "function") {
    proto.hasPointerCapture = () => false;
    proto.setPointerCapture = () => undefined;
    proto.releasePointerCapture = () => undefined;
  }
}

installPointerCaptureShims();

async function selectTimelineFilter(container: HTMLElement, label: string) {
  const trigger = container.querySelector<HTMLElement>('[data-vui-select-trigger="true"]');
  expect(trigger).toBeTruthy();
  await act(async () => {
    trigger!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
  });
  let option = Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]'))
    .find((item) => item.textContent?.includes(label));
  if (!option) {
    await act(async () => {
      trigger!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    option = Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]'))
      .find((item) => item.textContent?.includes(label));
  }
  expect(option).toBeTruthy();
  await act(async () => {
    option!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

it("starts with actionable events and can inspect successful details without an error alert", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const run = { events: [
    { eventId: "ok", type: "node_succeeded", occurredAt: "2026-09-05T12:00:00Z", payload: { nodeId: "problem_analysis", detail: "已核验" } },
    { eventId: "fail", type: "node_failed", occurredAt: "2026-09-05T12:01:00Z", payload: { nodeId: "hypothesis_design", detail: "执行失败" } },
  ] } as unknown as WorkflowRunRecord;
  try {
    await act(async () => root.render(<ResearchRunTimeline run={run} projection={null} insights={{} as ResearchWorkflowInsights} selectedNodeId="problem_analysis" />));
    expect(container.textContent).toContain("节点失败");
    expect(container.textContent).not.toContain("节点已完成");
    expect(container.innerHTML.indexOf("运行时间线")).toBeLessThan(container.innerHTML.indexOf("关键路径"));
    await selectTimelineFilter(container, "所选节点");
    expect(container.textContent).toContain("节点已完成");
    expect(container.textContent).not.toContain("节点失败");
    const detail = container.querySelector('[data-vui="error-summary"]')!;
    expect(detail.getAttribute("data-tone")).toBe("info");
    expect(detail.getAttribute("role")).toBe("status");
    await selectTimelineFilter(container, "全部事件");
    expect(container.querySelectorAll("time")).toHaveLength(2);
  } finally { await act(async () => root.unmount()); container.remove(); }
});
