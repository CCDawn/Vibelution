/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversationRerunFileChoiceDialog } from "./ConversationRerunFileChoiceDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function textContent(): string {
  return document.body.textContent ?? "";
}

function buttonByText(text: string): HTMLButtonElement | null {
  return Array.from(document.querySelectorAll("button"))
    .find((button) => (button.textContent ?? "").includes(text)) ?? null;
}

describe("ConversationRerunFileChoiceDialog", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    document.body.innerHTML = "";
    root = null;
  });

  async function mount(props: Partial<React.ComponentProps<typeof ConversationRerunFileChoiceDialog>> = {}) {
    const onOpenChange = props.onOpenChange ?? vi.fn();
    const onRestoreAndRerun = props.onRestoreAndRerun ?? vi.fn();
    const onRerunOnly = props.onRerunOnly ?? vi.fn();
    await act(async () => {
      root = createRoot(document.body);
      root.render(
        <ConversationRerunFileChoiceDialog
          open
          language="zh"
          paths={["src/a.ts", "src/b.ts"]}
          pending={false}
          error=""
          onOpenChange={onOpenChange}
          onRestoreAndRerun={onRestoreAndRerun}
          onRerunOnly={onRerunOnly}
          {...props}
        />,
      );
    });
    return { onOpenChange, onRestoreAndRerun, onRerunOnly };
  }

  it("lists the files and offers restore, rerun, or cancel", async () => {
    const handlers = await mount();

    expect(document.querySelector("[data-vui='conversation-rerun-file-choice']")).not.toBeNull();
    expect(textContent()).toContain("重跑前要不要还原文件？");
    expect(textContent()).toContain("src/a.ts");
    expect(textContent()).toContain("src/b.ts");

    await act(async () => {
      buttonByText("只重跑")?.click();
    });
    expect(handlers.onRerunOnly).toHaveBeenCalledTimes(1);

    await act(async () => {
      buttonByText("还原文件并重跑")?.click();
    });
    expect(handlers.onRestoreAndRerun).toHaveBeenCalledTimes(1);

    await act(async () => {
      buttonByText("取消")?.click();
    });
    expect(handlers.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows an English choice and caps the path list at eight", async () => {
    const paths = Array.from({ length: 9 }, (_, index) => `src/file-${index}.ts`);
    await mount({ language: "en", paths, error: "Another program changed src/file-0.ts" });

    expect(textContent()).toContain("Restore files before rerunning?");
    expect(textContent()).toContain("Rerun only");
    expect(textContent()).toContain("Restore files and rerun");
    expect(textContent()).toContain("src/file-0.ts");
    expect(textContent()).toContain("src/file-7.ts");
    expect(textContent()).not.toContain("src/file-8.ts");
    expect(textContent()).toContain("1 more");
    expect(textContent()).toContain("Another program changed src/file-0.ts");
  });

  it("disables every choice while files are restoring", async () => {
    const handlers = await mount({ pending: true });

    expect(textContent()).toContain("正在还原文件…");
    expect(buttonByText("正在还原文件…")?.disabled).toBe(true);
    expect(buttonByText("只重跑")?.disabled).toBe(true);
    expect(buttonByText("取消")?.disabled).toBe(true);

    await act(async () => {
      buttonByText("正在还原文件…")?.click();
      buttonByText("只重跑")?.click();
      buttonByText("取消")?.click();
    });
    expect(handlers.onRestoreAndRerun).not.toHaveBeenCalled();
    expect(handlers.onRerunOnly).not.toHaveBeenCalled();
    expect(handlers.onOpenChange).not.toHaveBeenCalled();
  });
});
