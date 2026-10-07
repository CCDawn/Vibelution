// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { SessionSummary } from "../../api/types";
import { FinanceResearchHistory } from "./FinanceResearchHistory";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let node: HTMLDivElement;

const record: SessionSummary = {
  id: "finance-session",
  title: "特别长的财报研究标题用于确认省略提示会保留完整内容",
  agentId: "finance",
  status: "completed",
  taskSummary: "已完成摘要",
  lastActive: "",
  updatedAt: "2026-10-06T10:00:00.000Z",
  currentPhase: "ready",
  terminalReason: "success",
};

beforeEach(() => {
  node = document.createElement("div");
  document.body.appendChild(node);
  root = createRoot(node);
});
afterEach(async () => {
  await act(async () => root.unmount());
  node.remove();
});

async function render(props: Partial<React.ComponentProps<typeof FinanceResearchHistory>> = {}) {
  await act(async () => root.render(<FinanceResearchHistory
    records={[record]} selectedId={record.id} onOpen={() => {}} zh compact {...props}
  />));
}

describe("financial research history rows", () => {
  it("keeps the title, accessible status, and session menu in a compact row", async () => {
    await render({ onAction: () => {} });
    const title = node.querySelector("strong[title]");
    const status = node.querySelector<HTMLElement>("[data-status]");
    const recordButton = status?.closest("button");
    const menu = node.querySelector<HTMLButtonElement>('button[aria-label^="管理研究："]');
    const row = recordButton?.parentElement;

    expect(title?.title).toBe(record.title);
    expect(status?.dataset.status).toBe("Completed");
    expect(status?.title).toBe("已完成");
    expect(status?.querySelector(".sr-only")?.textContent).toBe("已完成");
    expect(recordButton?.className).toContain("!min-h-8");
    expect(menu).not.toBeNull();
    expect(row?.className).toContain("last-child");
  });

  it.each([
    ["completed", "Completed"],
    ["running", "Running"],
    ["stopping", "Stopping"],
    ["ready", "Research session"],
    ["failed", "Failed"],
  ])("maps the native %s status to its own status icon", async (nativeStatus, label) => {
    await render({ records: [{ ...record, status: nativeStatus, terminalReason: nativeStatus === "ready" ? undefined : record.terminalReason }] });
    const status = node.querySelector<HTMLElement>("[data-status]");
    expect(status?.dataset.status).toBe(label);
    expect(status?.querySelector("svg")).not.toBeNull();
    expect(status?.querySelector(".sr-only")?.textContent).toBeTruthy();
  });

  it("shows full body-search snippets with normal line breaks below the one-line metadata", async () => {
    await render({
      compact: false,
      searchValue: "现金流",
      records: [{ ...record, searchSnippets: ["经营现金流明显改善\n原文第63页披露回款增加"] }],
    });
    const title = node.querySelector<HTMLElement>("strong[title]");
    const heading = title?.parentElement;
    const preview = [...node.querySelectorAll<HTMLElement>("span")].find((element) => element.textContent === "经营现金流明显改善\n原文第63页披露回款增加");

    expect(title?.title).toBe(record.title);
    expect(heading?.querySelector("[data-status]")?.dataset.status).toBe("Completed");
    expect(heading?.querySelector("time")?.dateTime).toBe(record.updatedAt);
    expect(preview?.textContent).toBe("经营现金流明显改善\n原文第63页披露回款增加");
    expect(preview?.className).toContain("whitespace-pre-wrap");
  });
});
