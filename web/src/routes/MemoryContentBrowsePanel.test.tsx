import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MemoryContentBrowsePanel, type MemoryContentBrowsePanelCopy } from "./MemoryContentBrowsePanel";

const copy: MemoryContentBrowsePanelCopy = {
  loading: "正在加载",
  loadFailed: "加载失败",
  browseBack: "返回卡片",
  browseSelectCard: "选择一张卡片",
  browseEmptyCards: "暂无卡片",
  browseEmptyEntries: "暂无条目",
  noContent: "无内容",
  searchPlaceholder: "搜索",
  ungrouped: "其他",
  expandGroup: "展开",
  collapseGroup: "收起",
};

const cards = [
  { id: "a1", title: "工作 Agent", group: "有记忆", meta: "对话 · 2 条记忆" },
  { id: "b1", title: "休眠 Agent", group: "暂无记忆", meta: "通用 · 0 条记忆" },
  { id: "b2", title: "另一个 Agent", group: "暂无记忆", meta: "研究 · 0 条记忆" },
];

function renderPanel(overrides: Partial<React.ComponentProps<typeof MemoryContentBrowsePanel>> = {}) {
  return renderToStaticMarkup(
    <MemoryContentBrowsePanel
      copy={copy}
      cards={cards}
      selectedCardId=""
      onSelectCard={() => {}}
      onClearCard={() => {}}
      entries={[]}
      selectedEntryId=""
      onSelectEntry={() => {}}
      {...overrides}
    />,
  );
}

describe("MemoryContentBrowsePanel collapsible groups", () => {
  it("renders the optional empty-cards hint with the empty state", () => {
    const markup = renderPanel({
      cards: [],
      copy: { ...copy, browseEmptyCardsHint: "可在「团队」页面打开团队知识库" },
    });
    expect(markup).toContain("暂无卡片");
    expect(markup).toContain("可在「团队」页面打开团队知识库");
  });

  it("renders every group expanded when no collapsible titles are configured", () => {
    const markup = renderPanel();
    expect(markup).toContain("工作 Agent");
    expect(markup).toContain("休眠 Agent");
    expect(markup).not.toContain("展开");
  });

  it("keeps a collapsible group closed until the user expands it", () => {
    const markup = renderPanel({ collapsibleGroupTitles: ["暂无记忆"] });
    expect(markup).toContain("工作 Agent");
    expect(markup).toContain("暂无记忆");
    expect(markup).toContain("展开");
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).not.toContain("休眠 Agent");
  });

  it("reveals collapsed matches while a search is active", () => {
    const markup = renderPanel({ collapsibleGroupTitles: ["暂无记忆"], searchText: "休眠" });
    expect(markup).toContain("休眠 Agent");
    expect(markup).not.toContain("展开");
  });
});
