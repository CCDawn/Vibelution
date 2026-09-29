/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversationFollowupQueueBar } from "./ConversationFollowupQueueBar";
import type { ComposerQueueItem } from "./composerFollowupQueueModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DRAG_LABEL = "拖动排序";
const EDIT_LABEL = "修改这条排队";
const WITHDRAW_LABEL = "撤回这条排队";
const SAVE_LABEL = "保存修改";
const CANCEL_LABEL = "放弃修改";

function setNativeValue(element: HTMLInputElement, value: string) {
  const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
  proto?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

/**
 * happy-dom has no real HTML5 drag-and-drop; drive the React handlers with
 * bubbling events carrying a minimal dataTransfer stub, matching what a real
 * Chromium drag sequence dispatches.
 */
function fireDrag(element: Element, type: "dragstart" | "dragover" | "drop" | "dragend") {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", {
    value: {
      setData: () => undefined,
      setDragImage: () => undefined,
      dropEffect: "move",
      effectAllowed: "all",
    },
  });
  element.dispatchEvent(event);
}

describe("ConversationFollowupQueueBar inline edit", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  async function renderBar(options: {
    items: ComposerQueueItem[];
    onUpdate?: (id: string, text: string) => void;
    onMove?: (fromIndex: number, toIndex: number) => void;
  }) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={options.items}
          lang="zh"
          editLabel={EDIT_LABEL}
          withdrawLabel={WITHDRAW_LABEL}
          saveEditLabel={SAVE_LABEL}
          cancelEditLabel={CANCEL_LABEL}
          dragHandleLabel={DRAG_LABEL}
          onUpdate={options.onUpdate ?? (() => undefined)}
          onRemove={() => undefined}
          onMove={options.onMove ?? (() => undefined)}
        />,
      );
    });
  }

  it("saves an edit through the queue update path", async () => {
    const onUpdate = vi.fn();
    await renderBar({
      items: [{ id: "q-1", text: "先不要改测试" }],
      onUpdate,
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>(`button[aria-label="${EDIT_LABEL}"]`)?.click();
    });
    const editor = container?.querySelector<HTMLInputElement>(`input[aria-label="${EDIT_LABEL} 1"]`);
    expect(editor).toBeTruthy();
    expect(editor?.value).toBe("先不要改测试");
    await act(async () => {
      setNativeValue(editor!, "只汇报改了哪些文件");
      const save = Array.from(container?.querySelectorAll("button") ?? []).find(
        (button) => button.textContent === SAVE_LABEL,
      );
      save?.click();
    });
    expect(onUpdate).toHaveBeenCalledWith("q-1", "只汇报改了哪些文件");
    expect(container?.querySelector(`input[aria-label="${EDIT_LABEL} 1"]`)).toBeNull();
  });

  it("cancels an edit via the cancel button without updating", async () => {
    const onUpdate = vi.fn();
    await renderBar({
      items: [{ id: "q-1", text: "先不要改测试" }],
      onUpdate,
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>(`button[aria-label="${EDIT_LABEL}"]`)?.click();
    });
    await act(async () => {
      const editor = container?.querySelector<HTMLInputElement>(`input[aria-label="${EDIT_LABEL} 1"]`);
      setNativeValue(editor!, "改一半就放弃");
      const cancel = Array.from(container?.querySelectorAll("button") ?? []).find(
        (button) => button.textContent === CANCEL_LABEL,
      );
      cancel?.click();
    });
    expect(onUpdate).not.toHaveBeenCalled();
    expect(container?.querySelector(`input[aria-label="${EDIT_LABEL} 1"]`)).toBeNull();
  });

  it("cancels an edit on Escape without updating", async () => {
    const onUpdate = vi.fn();
    await renderBar({
      items: [{ id: "q-1", text: "先不要改测试" }],
      onUpdate,
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>(`button[aria-label="${EDIT_LABEL}"]`)?.click();
    });
    await act(async () => {
      const editor = container?.querySelector<HTMLInputElement>(`input[aria-label="${EDIT_LABEL} 1"]`);
      setNativeValue(editor!, "按 Esc 放弃");
      editor?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(onUpdate).not.toHaveBeenCalled();
    expect(container?.querySelector(`input[aria-label="${EDIT_LABEL} 1"]`)).toBeNull();
  });

  it("saves an edit on Enter", async () => {
    const onUpdate = vi.fn();
    await renderBar({
      items: [{ id: "q-1", text: "先不要改测试" }],
      onUpdate,
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>(`button[aria-label="${EDIT_LABEL}"]`)?.click();
    });
    await act(async () => {
      const editor = container?.querySelector<HTMLInputElement>(`input[aria-label="${EDIT_LABEL} 1"]`);
      setNativeValue(editor!, "按 Enter 保存");
      editor?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    expect(onUpdate).toHaveBeenCalledWith("q-1", "按 Enter 保存");
  });
});

describe("ConversationFollowupQueueBar drag reorder", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  function rows(): HTMLElement[] {
    const rowsHost = container?.querySelector(".followupQueueRows");
    return Array.from(rowsHost?.children ?? []) as HTMLElement[];
  }

  function handleAt(index: number): HTMLButtonElement | null {
    return rows()[index]?.querySelector<HTMLButtonElement>(`button[aria-label="${DRAG_LABEL}"]`) ?? null;
  }

  async function renderBar(options: {
    items: ComposerQueueItem[];
    onMove?: (fromIndex: number, toIndex: number) => void;
  }) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={options.items}
          lang="zh"
          editLabel={EDIT_LABEL}
          withdrawLabel={WITHDRAW_LABEL}
          saveEditLabel={SAVE_LABEL}
          cancelEditLabel={CANCEL_LABEL}
          dragHandleLabel={DRAG_LABEL}
          onUpdate={() => undefined}
          onRemove={() => undefined}
          onMove={options.onMove ?? (() => undefined)}
        />,
      );
    });
  }

  it("moves a row via the handle drag sequence through onMove", async () => {
    const onMove = vi.fn();
    await renderBar({
      items: [
        { id: "q-1", text: "第一条" },
        { id: "q-2", text: "第二条" },
        { id: "q-3", text: "第三条" },
      ],
      onMove,
    });

    const source = handleAt(2)!;
    await act(async () => {
      fireDrag(source, "dragstart");
    });
    expect(container?.querySelector('[data-queue-drag-active="true"]')).not.toBeNull();
    expect(rows()[2].className).toContain("followupQueueRowDragSource");

    await act(async () => {
      fireDrag(rows()[0], "dragover");
    });
    // Dropping upward lands the item before the hovered row.
    expect(rows()[0].className).toContain("followupQueueRowDropBefore");
    expect(rows()[0].className).not.toContain("followupQueueRowDropAfter");

    await act(async () => {
      fireDrag(rows()[0], "drop");
    });
    expect(onMove).toHaveBeenCalledTimes(1);
    expect(onMove).toHaveBeenCalledWith(2, 0);
    expect(container?.querySelector('[data-queue-drag-active="true"]')).toBeNull();
    expect(rows()[0].className).not.toContain("followupQueueRowDropBefore");
  });

  it("shows the below-insertion indicator when dragging downward", async () => {
    const onMove = vi.fn();
    await renderBar({
      items: [
        { id: "q-1", text: "第一条" },
        { id: "q-2", text: "第二条" },
        { id: "q-3", text: "第三条" },
      ],
      onMove,
    });

    await act(async () => {
      fireDrag(handleAt(0)!, "dragstart");
      fireDrag(rows()[2], "dragover");
    });
    expect(rows()[2].className).toContain("followupQueueRowDropAfter");
    expect(rows()[2].className).not.toContain("followupQueueRowDropBefore");

    await act(async () => {
      fireDrag(rows()[2], "drop");
    });
    expect(onMove).toHaveBeenCalledWith(0, 2);
  });

  it("freezes row hover feedback while a drag is active", async () => {
    await renderBar({
      items: [
        { id: "q-1", text: "第一条" },
        { id: "q-2", text: "第二条" },
      ],
    });

    await act(async () => {
      fireDrag(handleAt(0)!, "dragstart");
    });
    for (const row of rows()) {
      expect(row.className).toContain("followupQueueRowDragLock");
      const actions = row.querySelector('[class*="followupQueueRowActions"]');
      expect(actions?.className).toContain("followupQueueRowActionsDragLock");
    }

    await act(async () => {
      fireDrag(handleAt(0)!, "dragend");
    });
    for (const row of rows()) {
      expect(row.className).not.toContain("followupQueueRowDragLock");
    }
  });

  it("never renders a draggable handle while the row is being edited", async () => {
    await renderBar({
      items: [
        { id: "q-1", text: "第一条" },
        { id: "q-2", text: "第二条" },
      ],
    });

    await act(async () => {
      rows()[0].querySelector<HTMLButtonElement>(`button[aria-label="${EDIT_LABEL}"]`)?.click();
    });
    expect(container?.querySelector(`input[aria-label="${EDIT_LABEL} 1"]`)).not.toBeNull();
    // Edited row: grip falls back to the inert decoration span.
    expect(rows()[0].querySelector(`button[aria-label="${DRAG_LABEL}"]`)).toBeNull();
    expect(rows()[0].querySelector('[aria-hidden="true"]')).not.toBeNull();
    // Untouched rows stay draggable.
    expect(handleAt(1)).not.toBeNull();
  });

  it("keeps a single-row queue without a draggable handle", async () => {
    const onMove = vi.fn();
    await renderBar({ items: [{ id: "q-1", text: "唯一一条" }], onMove });

    expect(handleAt(0)).toBeNull();
    expect(container?.querySelector('[aria-label="待发送队列"]')).not.toBeNull();
  });

  it("renders no queue at all for an empty list", async () => {
    await renderBar({ items: [] });
    expect(container?.querySelector('[aria-label="待发送队列"]')).toBeNull();
  });

  it("reorders with ArrowUp/ArrowDown on the focused handle", async () => {
    const onMove = vi.fn();
    await renderBar({
      items: [
        { id: "q-1", text: "第一条" },
        { id: "q-2", text: "第二条" },
        { id: "q-3", text: "第三条" },
      ],
      onMove,
    });

    await act(async () => {
      handleAt(1)!.focus();
      handleAt(1)!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }));
    });
    expect(onMove).toHaveBeenCalledWith(1, 0);

    await act(async () => {
      handleAt(0)!.focus();
      handleAt(0)!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    });
    expect(onMove).toHaveBeenCalledWith(0, 1);

    onMove.mockClear();
    await act(async () => {
      handleAt(0)!.focus();
      handleAt(0)!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }));
      handleAt(2)!.focus();
      handleAt(2)!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    });
    expect(onMove).not.toHaveBeenCalled();
  });

  it("ignores drops on the source row itself", async () => {
    const onMove = vi.fn();
    await renderBar({
      items: [
        { id: "q-1", text: "第一条" },
        { id: "q-2", text: "第二条" },
      ],
      onMove,
    });

    await act(async () => {
      fireDrag(handleAt(1)!, "dragstart");
      fireDrag(rows()[1], "dragover");
      fireDrag(rows()[1], "drop");
    });
    expect(onMove).not.toHaveBeenCalled();
  });
});
