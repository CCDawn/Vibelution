/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { ConversationToolActivity } from "./ConversationToolActivity";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { createCodexTranscriptToolActivity } from "./conversationToolActivityModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function toolCell(id: string, summary: string): CodexTranscriptCell {
  return {
    id,
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    title: "code_symbol_tool",
    summary,
  };
}

function namedToolCell(id: string, rawToolName: string): CodexTranscriptCell {
  const cell = toolCell(id, "已完成");
  cell.title = rawToolName;
  return cell;
}

function mountActivity(cells: CodexTranscriptCell[]) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const render = () => root.render(
    <ConversationToolActivity
      activity={createCodexTranscriptToolActivity(cells)}
      language="zh"
      renderToolDetails={(cell) => <pre>{`详情 ${cell.id}`}</pre>}
    />,
  );
  const unmount = async () => {
    await act(async () => root.unmount());
    host.remove();
  };
  return { host, render, unmount };
}

describe("ConversationToolActivity row open persistence", () => {
  it("starts collapsed, expands on toggle, and delays body unmount after collapse", async () => {
    const { host, render, unmount } = mountActivity([toolCell("persist-timing-1", "已完成")]);
    await act(async () => render());

    const details = host.querySelector("details")!;
    expect(details.hasAttribute("open")).toBe(false);
    // Client rows start collapsed: the body is not mounted at all.
    expect(host.querySelector('[data-codex-tool-detail-body="true"]')).toBeNull();

    await act(async () => host.querySelector("summary")!.click());
    expect(details.hasAttribute("open")).toBe(true);
    const body = host.querySelector('[data-codex-tool-detail-body="true"]')!;
    expect(body.textContent).toContain("详情 persist-timing-1");

    await act(async () => host.querySelector("summary")!.click());
    expect(details.hasAttribute("open")).toBe(false);
    // Within the unmount delay the body stays mounted (no flash on re-expand).
    expect(host.querySelector('[data-codex-tool-detail-body="true"]')).not.toBeNull();
    await act(async () => new Promise((resolve) => setTimeout(resolve, 360)));
    expect(host.querySelector('[data-codex-tool-detail-body="true"]')).toBeNull();

    await unmount();
  });

  it("persists the user's expand/collapse choice across unmount and remount", async () => {
    const cell = toolCell("persist-remount-1", "已完成");
    const first = mountActivity([cell]);
    await act(async () => first.render());
    await act(async () => first.host.querySelector("summary")!.click());
    expect(first.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    await first.unmount();

    const second = mountActivity([cell]);
    await act(async () => second.render());
    expect(second.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    expect(second.host.querySelector('[data-codex-tool-detail-body="true"]')?.textContent)
      .toContain("详情 persist-remount-1");

    await act(async () => second.host.querySelector("summary")!.click());
    expect(second.host.querySelector("details")!.hasAttribute("open")).toBe(false);
    await second.unmount();

    const third = mountActivity([cell]);
    await act(async () => third.render());
    expect(third.host.querySelector("details")!.hasAttribute("open")).toBe(false);
    await third.unmount();
  });

  it("reveals the failure copy affordance with the full error once expanded", async () => {
    const failedCell = toolCell("persist-failed-1", "HTTP 406: https://elifesciences.org/articles/13810");
    failedCell.status = "failed";
    failedCell.tone = "error";

    const { host, render, unmount } = mountActivity([failedCell]);
    await act(async () => render());

    // Hover language first: the status word carries the VTooltip trigger slot
    // (error summary mounts on hover; native title is gone by contract).
    const statusPill = host.querySelector('[data-codex-tool-status-pill="true"]')!;
    expect(statusPill.getAttribute("data-slot")).toBe("tooltip-trigger");
    expect(host.querySelector('[data-codex-tool-failure-copy="true"]')).toBeNull();

    await act(async () => host.querySelector("summary")!.click());
    const copySlot = host.querySelector('[data-codex-tool-failure-copy="true"]')!;
    expect(copySlot).not.toBeNull();
    expect(host.querySelector("details")!.textContent).toContain("HTTP 406: https://elifesciences.org/articles/13810");

    await unmount();
  });

  it("persists the category group's expand choice across unmount and remount", async () => {
    const cells = [
      namedToolCell("group-persist-read-1", "read_file_tool"),
      namedToolCell("group-persist-grep-1", "grep_search_tool"),
    ];
    const first = mountActivity(cells);
    await act(async () => first.render());

    const group = first.host.querySelector('[data-codex-tool-activity-category-group="true"]')!;
    expect(group.hasAttribute("open")).toBe(false);
    // Children stay unmounted while collapsed.
    expect(first.host.querySelector('[data-codex-tool-detail="true"]')).toBeNull();

    await act(async () => group.querySelector("summary")!.click());
    expect(group.hasAttribute("open")).toBe(true);
    expect(first.host.querySelector('[data-codex-tool-detail="true"]')).not.toBeNull();
    await first.unmount();

    const second = mountActivity(cells);
    await act(async () => second.render());
    const reopened = second.host.querySelector('[data-codex-tool-activity-category-group="true"]')!;
    expect(reopened.hasAttribute("open")).toBe(true);
    expect(second.host.querySelector('[data-codex-tool-detail="true"]')).not.toBeNull();

    await act(async () => reopened.querySelector("summary")!.click());
    expect(reopened.hasAttribute("open")).toBe(false);
    await second.unmount();
  });
});
