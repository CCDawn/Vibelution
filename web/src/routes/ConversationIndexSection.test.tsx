import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationIndexSection } from "./ConversationIndexSection";

describe("ConversationIndexSection", () => {
  it("renders a compact expandable group header with count", () => {
    const markup = renderToStaticMarkup(
      <ConversationIndexSection
        count={3}
        expanded
        label="用户会话"
        onToggle={() => undefined}
      >
        <span>会话 A</span>
      </ConversationIndexSection>,
    );

    expect(markup).toContain("aria-expanded=\"true\"");
    expect(markup).toContain("用户会话");
    expect(markup).toContain("<strong>3</strong>");
    expect(markup).toContain("会话 A");
  });

  it("keeps collapsed group contents out of the rendered list", () => {
    const markup = renderToStaticMarkup(
      <ConversationIndexSection
        count={1}
        expanded={false}
        label="团队"
        onToggle={() => undefined}
      >
        <span>隐藏内容</span>
      </ConversationIndexSection>,
    );

    expect(markup).toContain("aria-expanded=\"false\"");
    expect(markup).toContain("团队");
    expect(markup).not.toContain("隐藏内容");
  });
});
