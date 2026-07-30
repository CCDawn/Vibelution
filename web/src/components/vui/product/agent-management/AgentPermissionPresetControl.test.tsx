import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  AgentPermissionPresetControl,
  agentPermissionPresetOptions,
} from "./AgentPermissionPresetControl";

describe("AgentPermissionPresetControl", () => {
  it("exposes exactly the three Agent-owned permission presets", () => {
    expect(agentPermissionPresetOptions("zh").map((option) => option.value)).toEqual([
      "request_approval",
      "auto_review",
      "full_access",
    ]);
    expect(agentPermissionPresetOptions("zh").map((option) => option.label)).toEqual([
      "请求批准",
      "替我审批",
      "完全访问权限",
    ]);
    expect(agentPermissionPresetOptions("zh")).toHaveLength(3);
  });

  it("renders a compact Codex-style trigger without a custom mode", () => {
    const html = renderToStaticMarkup(
      <AgentPermissionPresetControl
        value="full_access"
        lang="zh"
        surface="composer"
        disabled={false}
        pending={false}
        onChange={() => undefined}
      />,
    );

    expect(html).toContain("完全访问权限");
    expect(html).toContain('aria-haspopup="listbox"');
    expect(html).toContain('data-surface="composer"');
    expect(html).not.toContain("自定义");
    expect(html).not.toContain("config.toml");
  });
});
