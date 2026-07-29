import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TeamCandidateCard } from "./TeamCandidateCard";
import { TeamSourceResultItem } from "./TeamSourceResultList";

function articleOpeningTag(markup: string) {
  return markup.match(/<article\b[^>]*>/)?.[0] ?? "";
}

describe("team management product interaction semantics", () => {
  it("keeps candidate card actions outside the dedicated activation button", () => {
    const markup = renderToStaticMarkup(
      React.createElement(TeamCandidateCard, {
        title: "候选资料",
        statusLabel: "待复核",
        tone: "warning",
        selected: true,
        onActivate: () => undefined,
        activateTitle: "打开候选资料",
        actions: React.createElement("button", { type: "button" }, "通过复核"),
      }),
    );

    expect(articleOpeningTag(markup)).not.toContain('role="button"');
    expect(articleOpeningTag(markup)).not.toContain('tabindex="0"');
    expect(markup).toContain('data-vui="native-button"');
    expect(markup).toContain('aria-pressed="true"');
    expect(markup).toContain("打开候选资料");
    expect(markup).toContain("通过复核");
  });

  it("uses a dedicated activation button without wrapping the provenance link", () => {
    const markup = renderToStaticMarkup(
      React.createElement(TeamSourceResultItem, {
        tone: "ready",
        statusLabel: "已提炼",
        title: "资料标题",
        meta: [{ key: "time", label: "12:40" }],
        source: {
          label: "DOI",
          value: "10.1000/example",
          href: "https://doi.org/10.1000/example",
        },
        selected: false,
        onActivate: () => undefined,
        activateTitle: "打开资料详情",
      }),
    );

    expect(articleOpeningTag(markup)).not.toContain('role="button"');
    expect(articleOpeningTag(markup)).not.toContain('tabindex="0"');
    expect(markup).toContain('data-vui="native-button"');
    expect(markup).toContain('aria-pressed="false"');
    expect(markup).toContain("打开资料详情");
    expect(markup).toContain('href="https://doi.org/10.1000/example"');
  });
});
