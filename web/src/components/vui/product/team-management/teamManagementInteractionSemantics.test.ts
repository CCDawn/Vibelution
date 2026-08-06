import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TeamCandidateCard } from "./TeamCandidateCard";
import { TeamStageCard } from "./TeamStageCard";
import { TeamStageCommandBar } from "./TeamStageCommandBar";
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
    expect(markup).toContain('data-vui-product="team-status-label"');
    expect(markup).toContain('data-tone="warning"');
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
    expect(markup).toContain('data-vui-product="team-status-label"');
    expect(markup).toContain('data-tone="ready"');
    expect(markup).toContain('aria-pressed="false"');
    expect(markup).toContain("打开资料详情");
    expect(markup).toContain('href="https://doi.org/10.1000/example"');
  });

  it("keeps candidate supporting text out of the default row while preserving its source action", () => {
    const markup = renderToStaticMarkup(
      React.createElement(TeamCandidateCard, {
        title: "Isolation Forest 基线记录",
        statusLabel: "候选",
        tone: "ready",
        summary: "实验记录 · 质量 0.81",
        meta: [{ key: "owner", label: "实验 Agent" }],
        source: {
          label: "来源",
          value: "RUN-002",
          title: "运行 RUN-002",
          href: "https://example.test/runs/2",
        },
      }),
    );

    expect(markup).toContain("Isolation Forest 基线记录");
    expect(markup).toContain('href="https://example.test/runs/2"');
    expect(markup).toContain("lucide-external-link");
    expect(markup).not.toContain("实验记录 · 质量 0.81");
    expect(markup).not.toContain("实验 Agent");
    expect(markup).not.toContain(">RUN-002<");
  });

  it("keeps stage progress and command-bar support copy on hover instead of in the default frame", () => {
    const stageMarkup = renderToStaticMarkup(
      React.createElement(TeamStageCard, {
        index: 0,
        label: "知识采集",
        status: "当前",
        metric: "42 / 48",
        nextLabel: "完成交接",
        tone: "active",
        onActivate: () => undefined,
      }),
    );
    const commandMarkup = renderToStaticMarkup(
      React.createElement(TeamStageCommandBar, {
        title: "知识采集",
        subtitle: "知识需经人工确认才允许进入实验协议",
        tone: "active",
        stats: [],
        steps: [{ id: "collect", indexLabel: "01", title: "知识采集", tone: "active", status: "当前" }],
      }),
    );

    expect(stageMarkup).toContain("知识采集");
    expect(stageMarkup).toContain("当前");
    expect(stageMarkup).toContain('data-slot="stage-status"');
    expect(stageMarkup).not.toContain("rounded-full");
    expect(stageMarkup).not.toContain("42 / 48");
    expect(stageMarkup).not.toContain("完成交接");
    expect(commandMarkup).toContain("知识采集");
    expect(commandMarkup).toContain('title="当前"');
    expect(commandMarkup).not.toContain("知识需经人工确认才允许进入实验协议");
  });
});
