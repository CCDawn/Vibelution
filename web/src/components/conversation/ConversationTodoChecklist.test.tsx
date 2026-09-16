import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import { ConversationTodoChecklist } from "./ConversationTodoChecklist";
import type { TodoChecklistSnapshot } from "./conversationTodoChecklistModel";

function snapshot(overrides: Partial<TodoChecklistSnapshot> = {}): TodoChecklistSnapshot {
  return {
    items: [
      { content: "审查契约", activeForm: "正在审查契约", status: "completed" },
      { content: "补齐回归测试", activeForm: "正在补齐回归测试", status: "in_progress" },
      { content: "更新文档", activeForm: "正在更新文档", status: "pending" },
    ],
    completedCount: 1,
    total: 3,
    hasUnfinished: true,
    ...overrides,
  };
}

function renderCard(turnSettled: boolean, snap = snapshot(), lang: "zh" | "en" = "zh") {
  return renderToStaticMarkup(
    <ConversationTodoChecklist snapshot={snap} lang={lang} turnSettled={turnSettled} />,
  );
}

describe("ConversationTodoChecklist", () => {
  it("renders an expanded active card with spinner on the current activeForm row", () => {
    const html = renderCard(false);

    expect(html).toContain(dictionaryChat.zh.todoChecklistTitle);
    expect(html).toContain('data-testid="todo-checklist-counter"');
    expect(html).toContain(">1/3<");
    expect(html).toContain('data-todo-status="in_progress"');
    expect(html).toContain("正在补齐回归测试");
    expect(html).toContain("animate-spin");
    expect(html).toContain('data-todo-status="completed"');
    expect(html).toContain('data-todo-status="pending"');
    expect(html).toContain('data-testid="todo-checklist-items"');
  });

  it("shows completed checks and imperative content on finished rows", () => {
    const html = renderCard(false, snapshot({
      items: [{ content: "已完成项", activeForm: "正在完成", status: "completed" }],
      completedCount: 1,
      total: 1,
      hasUnfinished: false,
    }));

    expect(html).toContain("已完成项");
    expect(html).not.toContain("正在完成");
    expect(html).not.toContain("animate-spin");
  });

  it("warns on settled turns with unfinished items and collapses history by default", () => {
    const html = renderCard(true);

    expect(html).toContain('data-todo-checklist-settled="true"');
    expect(html).toContain('data-testid="todo-checklist-warning"');
    expect(html).toContain(dictionaryChat.zh.todoChecklistUnfinishedWarning);
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain('data-testid="todo-checklist-items"');
  });

  it("omits the warning once every item completed, even on settled turns", () => {
    const html = renderCard(true, snapshot({
      items: [{ content: "唯一项", activeForm: "正在做唯一项", status: "completed" }],
      completedCount: 1,
      total: 1,
      hasUnfinished: false,
    }));

    expect(html).not.toContain('data-testid="todo-checklist-warning"');
    expect(html).toContain(">1/1<");
  });

  it("localizes copy for english", () => {
    const html = renderCard(false, snapshot(), "en");

    expect(html).toContain(dictionaryChat.en.todoChecklistTitle);
    expect(html).not.toContain(dictionaryChat.zh.todoChecklistTitle);
  });
});
