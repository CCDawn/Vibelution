import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationIndexSection } from "./ConversationIndexSection";

describe("ConversationIndexSection", () => {
  it("renders a compact expandable group header with count", () => {
    const markup = renderToStaticMarkup(
      <ConversationIndexSection
        count={3}
        countLabel="3 个会话"
        expanded
        label="用户会话"
        onToggle={() => undefined}
      >
        <span>会话 A</span>
      </ConversationIndexSection>,
    );

    expect(markup).toContain("aria-expanded=\"true\"");
    expect(markup).toContain("aria-controls=");
    expect(markup).toContain("aria-labelledby=");
    expect(markup).toContain('role="group"');
    expect(markup).toContain('data-vui="native-button"');
    expect(markup).not.toContain('data-vui="button"');
    expect(markup).toContain("用户会话");
    expect(markup).toContain('title="3 个会话">3 个会话</span>');
    expect(markup).not.toContain("<strong>");
    expect(markup).toContain("会话 A");
  });

  it("keeps collapsed group contents out of the rendered list", () => {
    const markup = renderToStaticMarkup(
      <ConversationIndexSection
        count={1}
        countLabel="1 个 Agent"
        expanded={false}
        label="团队"
        onToggle={() => undefined}
      >
        <span>隐藏内容</span>
      </ConversationIndexSection>,
    );

    expect(markup).toContain("aria-expanded=\"false\"");
    expect(markup).toContain("aria-controls=");
    expect(markup).not.toContain('role="group"');
    expect(markup).toContain("团队");
    expect(markup).not.toContain("隐藏内容");
    expect(markup).not.toContain("1 个 Agent");
  });

  it("does not add an empty quantity to an expanded section", () => {
    const markup = renderToStaticMarkup(
      <ConversationIndexSection count={0} countLabel="0 个会话" expanded label="历史" onToggle={() => undefined}>
        <span>暂无会话</span>
      </ConversationIndexSection>,
    );
    expect(markup).toContain("暂无会话");
    expect(markup).not.toContain("0 个会话");
  });
});
