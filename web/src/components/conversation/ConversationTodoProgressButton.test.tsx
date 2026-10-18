import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationTodoProgressButton } from "./ConversationTodoProgressButton";
import type { SessionTodoChecklistProjection } from "./conversationTodoChecklistModel";

const plan: SessionTodoChecklistProjection = {
  messageId: "a1", turnSettled: false,
  snapshot: {
    items: [{ content: "补齐测试", activeForm: "正在补齐测试", status: "in_progress" }],
    completedCount: 0, total: 1, hasUnfinished: true,
  },
};
const render = (projection = plan, lang: "zh" | "en" = "zh") => renderToStaticMarkup(
  <ConversationTodoProgressButton plan={projection} lang={lang} expanded={false} onPress={() => {}} />,
);

describe("ConversationTodoProgressButton", () => {
  it("keeps the running plan entry enabled and exposes its progress", () => {
    const html = render();
    expect(html).toContain('data-todo-progress-status="running"');
    expect(html).toContain("animate-spin");
    expect(html).toContain('aria-label="任务清单 0/1 · 进行中"');
    expect(html).toContain('aria-controls="chat-status-pane"');
    expect(html).not.toMatch(/\sdisabled(?:=|[ >])/);
  });

  it("replaces a settled unfinished spinner with a visible continue label", () => {
    const html = render({ ...plan, turnSettled: true });
    expect(html).toContain('data-todo-progress-status="paused"');
    expect(html).toContain("待继续");
    expect(html).not.toContain("animate-spin");
  });

  it("marks completed and pending plans without a running indicator", () => {
    const completed = render({ ...plan, snapshot: {
      ...plan.snapshot, completedCount: 1, hasUnfinished: false,
      items: [{ ...plan.snapshot.items[0], status: "completed" }],
    } });
    expect(completed).toContain('data-todo-progress-status="completed"');
    expect(completed).toContain("1/1");
    expect(completed).not.toContain("animate-spin");
    const pending = render({ ...plan, snapshot: {
      ...plan.snapshot, items: [{ ...plan.snapshot.items[0], status: "pending" }],
    } }, "en");
    expect(pending).toContain('data-todo-progress-status="pending"');
    expect(pending).toContain("Not started");
    expect(pending).not.toContain("animate-spin");
  });
});
