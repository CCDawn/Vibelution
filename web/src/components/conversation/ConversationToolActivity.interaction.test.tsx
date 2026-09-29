/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ConversationToolActivity } from "./ConversationToolActivity";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { createCodexTranscriptToolActivity } from "./conversationToolActivityModel";
import {
  readOpenToolKeys,
  resetToolExpandPersistenceForTests,
  setToolRowOpen,
} from "./conversationToolExpandPersistence";

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

const DEFAULT_SESSION = "session-expand-tests";

function mountActivity(
  cells: CodexTranscriptCell[],
  options?: { sessionId?: string; turnFailed?: boolean },
) {
  const sessionId = options?.sessionId ?? DEFAULT_SESSION;
  const turnFailed = options?.turnFailed ?? false;
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  let current = cells;
  const render = (next?: CodexTranscriptCell[], nextTurnFailed?: boolean) => {
    if (next) {
      current = next;
    }
    root.render(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity(current)}
        language="zh"
        renderToolDetails={(cell) => <pre>{`详情 ${cell.id}`}</pre>}
        sessionId={sessionId}
        turnFailed={nextTurnFailed ?? turnFailed}
      />,
    );
  };
  const unmount = async () => {
    await act(async () => root.unmount());
    host.remove();
  };
  return { host, render, unmount };
}

beforeEach(() => {
  localStorage.clear();
  resetToolExpandPersistenceForTests();
});

afterEach(() => {
  localStorage.clear();
  resetToolExpandPersistenceForTests();
});

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

  it("survives a simulated page reload: the module cache is gone, localStorage remains", async () => {
    const cell = toolCell("persist-reload-1", "已完成");
    const first = mountActivity([cell]);
    await act(async () => first.render());
    await act(async () => first.host.querySelector("summary")!.click());
    expect(first.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    await first.unmount();

    // A reload drops every in-memory cache; only localStorage carries over.
    resetToolExpandPersistenceForTests();
    expect(readOpenToolKeys(DEFAULT_SESSION).has("persist-reload-1")).toBe(true);

    const second = mountActivity([cell]);
    await act(async () => second.render());
    expect(second.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    await second.unmount();
  });

  it("keeps expand state scoped per session", async () => {
    const cell = toolCell("persist-session-scope-1", "已完成");
    const other = mountActivity([cell], { sessionId: "session-other" });
    await act(async () => other.render());
    await act(async () => other.host.querySelector("summary")!.click());
    expect(other.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    await other.unmount();

    const sameCellDifferentSession = mountActivity([cell], { sessionId: "session-mine" });
    await act(async () => sameCellDifferentSession.render());
    expect(sameCellDifferentSession.host.querySelector("details")!.hasAttribute("open")).toBe(false);
    await sameCellDifferentSession.unmount();
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

describe("ConversationToolActivity failed-turn scene preservation", () => {
  it("force-opens the failed turn's rows, batches, and category groups initially", async () => {
    const single = mountActivity([toolCell("failed-scene-row", "已完成")], { turnFailed: true });
    await act(async () => single.render());
    expect(single.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    expect(single.host.querySelector('[data-codex-tool-detail-body="true"]')?.textContent)
      .toContain("详情 failed-scene-row");
    await single.unmount();

    // Same-name run folds into a batch; the batch and its rows open too.
    const batchCells = [
      namedToolCell("failed-scene-batch-1", "web_fetch_tool"),
      namedToolCell("failed-scene-batch-2", "web_fetch_tool"),
      namedToolCell("failed-scene-batch-3", "web_fetch_tool"),
    ];
    const batch = mountActivity(batchCells, { turnFailed: true });
    await act(async () => batch.render());
    expect(batch.host.querySelector('[data-codex-tool-activity-batch="true"]')!.hasAttribute("open")).toBe(true);
    await batch.unmount();

    // Distinct same-category tools escalate to a category group; it opens too.
    const groupCells = [
      namedToolCell("failed-scene-read", "read_file_tool"),
      namedToolCell("failed-scene-grep", "grep_search_tool"),
    ];
    const grouped = mountActivity(groupCells, { turnFailed: true });
    await act(async () => grouped.render());
    expect(grouped.host.querySelector('[data-codex-tool-activity-category-group="true"]')!.hasAttribute("open"))
      .toBe(true);
    await grouped.unmount();
  });

  it("force-opens over a stored collapsed choice, and the user may still close again", async () => {
    const cell = toolCell("failed-scene-vs-store-1", "已完成");
    // The user (or a previous view) left the row collapsed in storage.
    const mount = mountActivity([cell], { turnFailed: false });
    await act(async () => mount.render());
    await act(async () => mount.host.querySelector("summary")!.click());
    await act(async () => mount.host.querySelector("summary")!.click());
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(false);
    await mount.unmount();

    // Turn fails: the scene opens even though storage says collapsed…
    const failed = mountActivity([cell], { turnFailed: true });
    await act(async () => failed.render());
    expect(failed.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    // …and a manual collapse after the failure still wins.
    await act(async () => failed.host.querySelector("summary")!.click());
    expect(failed.host.querySelector("details")!.hasAttribute("open")).toBe(false);
    await failed.unmount();
  });

  it("keeps the failed turn's rows open across the running→settled edge (no auto-collapse)", async () => {
    const runningCell = toolCell("failed-scene-edge-1", "正在执行");
    runningCell.status = "running";
    runningCell.tone = "running";
    const settledCell = toolCell("failed-scene-edge-1", "已完成");

    const mount = mountActivity([runningCell], { turnFailed: false });
    await act(async () => mount.render());
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(false);

    // The turn fails as the row settles: force-open outranks the auto-collapse.
    await act(async () => mount.render([settledCell], true));
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(true);

    // Still open on later renders while the failure state holds.
    await act(async () => mount.render([settledCell], true));
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    await mount.unmount();
  });
});

describe("ConversationToolActivity complete-edge auto-collapse", () => {
  function runningCell(id: string): CodexTranscriptCell {
    const cell = toolCell(id, "正在执行");
    cell.status = "running";
    cell.tone = "running";
    return cell;
  }

  it("auto-collapses a persisted-open row once when it settles after running", async () => {
    // The row was expanded earlier and persisted; it mounts open while running.
    setToolRowOpen(DEFAULT_SESSION, "edge-auto-1", true);
    const mount = mountActivity([runningCell("edge-auto-1")]);
    await act(async () => mount.render());
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(true);

    // Settling auto-collapses once (the user did not touch the row this run).
    await act(async () => mount.render([toolCell("edge-auto-1", "已完成")]));
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(false);
    expect(readOpenToolKeys(DEFAULT_SESSION).has("edge-auto-1")).toBe(false);
    await mount.unmount();
  });

  it("respects a manual toggle made during the run and skips the auto-collapse", async () => {
    const mount = mountActivity([runningCell("edge-manual-1")]);
    await act(async () => mount.render());
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(false);

    // The user opens the row while it runs; settling must not close it.
    await act(async () => mount.host.querySelector("summary")!.click());
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(true);

    await act(async () => mount.render([toolCell("edge-manual-1", "已完成")]));
    expect(mount.host.querySelector("details")!.hasAttribute("open")).toBe(true);
    expect(readOpenToolKeys(DEFAULT_SESSION).has("edge-manual-1")).toBe(true);
    await mount.unmount();
  });

  it("auto-collapses the category group at the settle edge unless the user toggled it", async () => {
    const cells = (firstStatus: string) => [
      namedToolCell("edge-group-read-1", "read_file_tool"),
      (() => {
        const cell = namedToolCell("edge-group-grep-1", "grep_search_tool");
        if (firstStatus === "running") {
          cell.status = "running";
          cell.tone = "running";
        }
        return cell;
      })(),
    ];
    setToolRowOpen(DEFAULT_SESSION, "tool-category-group:edge-group-read-1", true);
    const mount = mountActivity(cells("running"));
    await act(async () => mount.render());
    const group = mount.host.querySelector('[data-codex-tool-activity-category-group="true"]')!;
    expect(group.hasAttribute("open")).toBe(true);

    // Group settles (its last child completed) → auto-collapse once.
    await act(async () => mount.render(cells("completed")));
    expect(
      mount.host.querySelector('[data-codex-tool-activity-category-group="true"]')!.hasAttribute("open"),
    ).toBe(false);
    await mount.unmount();

    // User-opened variant: toggle during running, settle keeps it open.
    setToolRowOpen(DEFAULT_SESSION, "tool-category-group:edge-group-read-1", false);
    const manual = mountActivity(cells("running"));
    await act(async () => manual.render());
    await act(async () => manual.host.querySelector('[data-codex-tool-activity-category-group="true"] summary')!.click());
    await act(async () => manual.render(cells("completed")));
    expect(
      manual.host.querySelector('[data-codex-tool-activity-category-group="true"]')!.hasAttribute("open"),
    ).toBe(true);
    await manual.unmount();
  });
});
