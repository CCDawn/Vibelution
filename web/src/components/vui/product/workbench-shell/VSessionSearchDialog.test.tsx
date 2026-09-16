/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VSessionSearchDialog, type VSessionSearchDialogItem } from "./VSessionSearchDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function item(overrides: Partial<VSessionSearchDialogItem> = {}): VSessionSearchDialogItem {
  return {
    id: "session-1",
    title: "接口重构会话",
    detail: "最后一条消息预览",
    meta: "知识管理员 · 已完成 · 2026-09-01",
    onOpen: vi.fn(),
    ...overrides,
  };
}

const labels = {
  searchPlaceholder: "搜索标题、摘要或会话编号",
  emptyTitle: "没有匹配的会话",
  emptyHint: "换个关键词",
  loadMore: "加载更多",
  loadingMore: "加载中…",
  resultSummary: (loaded: number, total: number) => `已加载 ${loaded} / ${total} 个会话`,
  hint: "↑↓ 选择 · Enter 打开 · Esc 关闭",
};

describe("VSessionSearchDialog", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("renders hit rows with query highlight, meta line and loaded/total summary", async () => {
    act(() => {
      root.render(
        <VSessionSearchDialog
          open
          onOpenChange={() => {}}
          query="重构"
          onQueryChange={() => {}}
          items={[item({ highlight: "重构" })]}
          totalEstimate={7}
          hasMore={false}
          labels={labels}
        />,
      );
    });
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("接口重构会话");
    });
    expect(document.body.textContent).toContain("最后一条消息预览");
    expect(document.body.textContent).toContain("知识管理员 · 已完成 · 2026-09-01");
    expect(document.body.textContent).toContain("已加载 1 / 7 个会话");
    const marks = Array.from(document.querySelectorAll("mark"));
    expect(marks.map((mark) => mark.textContent)).toEqual(["重构"]);
  });

  it("offers load-more while more pages remain and forwards the click", async () => {
    const onLoadMore = vi.fn();
    act(() => {
      root.render(
        <VSessionSearchDialog
          open
          onOpenChange={() => {}}
          query=""
          onQueryChange={() => {}}
          items={[item(), item({ id: "session-2", title: "第二条" })]}
          totalEstimate={52}
          hasMore
          loadingMore={false}
          onLoadMore={onLoadMore}
          labels={labels}
        />,
      );
    });
    const button = await vi.waitFor(() => {
      const found = Array.from(document.querySelectorAll("button")).find(
        (candidate) => candidate.textContent === "加载更多",
      );
      expect(found).toBeDefined();
      return found as HTMLButtonElement;
    });
    await act(async () => {
      button.click();
    });
    expect(onLoadMore).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain("已加载 2 / 52 个会话");
  });

  it("shows the empty state without results and hides load-more", async () => {
    act(() => {
      root.render(
        <VSessionSearchDialog
          open
          onOpenChange={() => {}}
          query="不存在的词"
          onQueryChange={() => {}}
          items={[]}
          totalEstimate={0}
          hasMore={false}
          labels={labels}
        />,
      );
    });
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("没有匹配的会话");
    });
    expect(document.body.textContent).toContain("换个关键词");
    expect(Array.from(document.querySelectorAll("button")).some((candidate) => candidate.textContent === "加载更多")).toBe(false);
  });

  it("opens the clicked row and closes the dialog", async () => {
    const onOpen = vi.fn();
    const onOpenChange = vi.fn();
    act(() => {
      root.render(
        <VSessionSearchDialog
          open
          onOpenChange={onOpenChange}
          query=""
          onQueryChange={() => {}}
          items={[item({ onOpen })]}
          totalEstimate={1}
          hasMore={false}
          labels={labels}
        />,
      );
    });
    const row = await vi.waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-index=\"0\"]");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    await act(async () => {
      row.click();
    });
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
