import { describe, expect, it } from "vitest";

import conversationTimelineItemsSource from "./conversationTimelineItems.tsx?raw";
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

  it("labels known read actions of the assistant action tool specifically", () => {
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "source_search" },
    })).toBe("搜索源码");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "source_read" },
    })).toBe("读取源码");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "session_list" },
    })).toBe("列出会话");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "task_list" },
    })).toBe("列出活跃任务");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "agent_list" },
    })).toBe("列出 Agent 目录");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "projects" },
    })).toBe("查询项目");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "receipt" },
    })).toBe("查询任务回执");
  });

  it("labels known manage actions of the assistant manage tool", () => {
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_manage_tool",
      commandSource: { action: "agent_create" },
    })).toBe("创建 Agent");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_manage_tool",
      commandSource: { action: "dispatch_write" },
    })).toBe("派遣 Agent 修改项目");
  });

  it("falls back to the tool-level label when the action is missing or unknown", () => {
    expect(conversationToolSemanticLabel({ toolName: "personal_assistant_action_tool" })).toBe("处理助理请求");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: {},
    })).toBe("处理助理请求");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "totally_unknown_action" },
    })).toBe("处理助理请求");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_manage_tool",
      commandSource: { action: 42 },
    })).toBe("执行助理操作");
  });

  it("never infers an assistant action from summary text or a serialized command source", () => {
    for (const commandSource of [undefined, '{"action":"agent_update"}', { action: "future_source_read" }]) {
      expect(conversationToolSemanticLabel({
        toolName: "personal_assistant_action_tool",
        summary: "source_read · 读取源码 · 已修改 Agent",
        commandSource,
      })).toBe("处理助理请求");
    }
  });

  it("reads the action from array-shaped command source like the native transcript path", () => {
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: [{ action: "source_search" }],
    })).toBe("搜索源码");
  });

  it("keeps the other personal_assistant tools on their static labels", () => {
    expect(conversationToolSemanticLabel({ toolName: "personal_assistant_query_tool" })).toBe("查询助理记录");
    expect(conversationToolSemanticLabel({ toolName: "personal_assistant_overview_tool" })).toBe("查看项目概况");
  });

  it("respects the requested language for assistant action labels", () => {
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      commandSource: { action: "source_search" },
      lang: "en",
    })).toBe("Search source");
    expect(conversationToolSemanticLabel({
      toolName: "personal_assistant_action_tool",
      lang: "en",
    })).toBe("Handle assistant request");
  });

  it("keeps the timeline wired to the action-aware labeler for assistant tools", () => {
    expect(conversationTimelineItemsSource).toContain('from "./conversationToolSemanticLabel"');
    expect(conversationTimelineItemsSource).toContain("commandSource: operation.arguments");
    expect(conversationTimelineItemsSource).toContain('startsWith("personal_assistant_")');
  });
});
