import { describe, expect, it } from "vitest";

import { conversationToolSemanticLabel } from "./conversationToolSemanticLabel";

describe("conversationToolSemanticLabel", () => {
  it.each([
    ["git status --short --branch", "检查 Git 状态"],
    ["git diff --stat", "查看 Git 变更"],
    ["git commit -m \"scope: update labels\"", "提交变更"],
    ["npx vitest run conversationToolSemanticLabel.test.ts", "运行测试"],
    ["npm --prefix web run build", "构建项目"],
    ["rg -n \"cli_tool\" web/src", "搜索代码"],
    ["Get-Content -LiteralPath package.json -Raw", "读取文件"],
    ["node scripts/custom-task.mjs", "执行命令"],
  ])("classifies cli_tool command %s", (commandSource, expected) => {
    expect(conversationToolSemanticLabel({
      toolName: "cli_tool",
      summary: "运行命令",
      commandSource,
    })).toBe(expected);
  });

  it("uses the fixed vocabulary without returning credential-bearing input fragments", () => {
    const sensitiveSources = [
      "TOKEN=super-secret node task.mjs",
      "tool.exe --password hunter2",
      "curl -H \"Authorization: Bearer abc.def.ghi\" https://example.com",
      "curl https://user:pass@example.com/private",
    ];

    for (const commandSource of sensitiveSources) {
      const label = conversationToolSemanticLabel({ toolName: "cli_tool", commandSource });
      expect(label).toBe("执行命令");
      expect(commandSource).not.toContain(label);
      expect(label).not.toMatch(/TOKEN|password|Bearer|super-secret|hunter2|abc\.def|user:pass/i);
    }
  });

  it("keeps the existing friendly labels for non-cli tools", () => {
    expect(conversationToolSemanticLabel({ toolName: "read_file_tool" })).toBe("读取文件");
    expect(conversationToolSemanticLabel({ toolName: "grep_search_tool" })).toBe("搜索");
    expect(conversationToolSemanticLabel({ toolName: "image2_generate_tool" })).toBe("生成图片");
  });
});
