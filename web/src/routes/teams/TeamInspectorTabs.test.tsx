/** @vitest-environment happy-dom */

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { TeamInspectorTabs, type TeamInspectorTabsProps } from "./TeamInspectorTabs";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("TeamInspectorTabs", () => {
  let host: HTMLDivElement;
  let root: Root | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    root = undefined;
  });

  function render(overrides: Partial<TeamInspectorTabsProps> = {}) {
    if (!root) {
      host = document.createElement("div");
      document.body.appendChild(host);
      root = createRoot(host);
    }
    act(() => root?.render(<TeamInspectorTabs
      lang="zh"
      selectedNodeId="node-a"
      members={<p>成员资料</p>}
      tasks={<textarea aria-label="任务草稿" defaultValue="" />}
      records={<p>真实通信记录</p>}
      {...overrides}
    />));
  }

  function select(label: string) {
    const tab = Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
      .find((element) => element.textContent === label);
    expect(tab).toBeTruthy();
    act(() => tab?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
  }

  function visibleSection() {
    return host.querySelector('[role="tabpanel"][data-state="active"] [data-team-inspector-section]')?.getAttribute("data-team-inspector-section");
  }

  it("starts on members and switches between all three sections", () => {
    render();
    expect(visibleSection()).toBe("members");
    select("任务");
    expect(visibleSection()).toBe("tasks");
    select("记录");
    expect(visibleSection()).toBe("records");
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe("记录");
    for (const tab of host.querySelectorAll('[role="tab"]')) {
      const panel = document.getElementById(tab.getAttribute("aria-controls")!);
      expect(panel?.getAttribute("role")).toBe("tabpanel");
      expect(panel?.getAttribute("aria-labelledby")).toBe(tab.id);
    }
  });

  it("keeps draft elements mounted when switching and when selecting a node", () => {
    render();
    select("任务");
    const input = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="任务草稿"]')!;
    input.value = "尚未提交的任务";
    select("记录");
    select("成员");
    select("任务");
    expect(host.querySelector("textarea")).toBe(input);
    expect(input.value).toBe("尚未提交的任务");
    render({ selectedNodeId: "node-b" });
    expect(visibleSection()).toBe("members");
    select("任务");
    expect(host.querySelector("textarea")).toBe(input);
    expect(input.value).toBe("尚未提交的任务");
  });

  it("returns to members on reselect, but an unrelated rerender preserves the tab", () => {
    render({ selectionRevision: 0 });
    select("记录");
    render({ selectionRevision: 0 });
    expect(visibleSection()).toBe("records");
    render({ selectionRevision: 1 });
    expect(visibleSection()).toBe("members");
  });
});
