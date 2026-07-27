import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionAgentPromptSnapshot, SessionPromptAssemblyManifest } from "../../api/types";
import { ChatPromptAssemblyInspector } from "./ChatPromptAssemblyInspector";

const snapshot: SessionAgentPromptSnapshot = {
  schemaVersion: 3,
  promptTemplateId: "prompt-chat-default",
  promptAssembly: {
    schemaVersion: 1,
    assemblyMode: "session_snapshot_v2",
    modelProtocol: "openai_chat",
    stablePrefixHash: "stable-safe",
    sessionSnapshotHash: "session-safe",
    totalEstimatedTokens: 128,
    budgetTokens: 512,
    segments: [
      {
        key: "core_common",
        tier: "stable_core",
        placement: "system_prefix",
        stability: "project_static",
        trust: "protected_core",
        source: "core/core_prompt/COMMON.md",
        required: true,
        chars: 320,
        contentHash: "common-safe",
        estimatedTokens: 80,
        budgetTokens: 0,
        cachePolicy: "prefix_candidate",
        capabilityRequirements: [],
        decision: "full",
        decisionReason: "snapshot",
      },
      {
        key: "agent_role_prompt",
        tier: "session_snapshot",
        placement: "system_prefix",
        stability: "session_static",
        trust: "operator_controlled",
        source: "prompt-chat-default",
        required: true,
        chars: 192,
        contentHash: "role-safe",
        estimatedTokens: 48,
        budgetTokens: 0,
        cachePolicy: "cacheable",
        capabilityRequirements: [],
        decision: "truncated",
        decisionReason: "budget",
      },
    ],
  },
};

describe("ChatPromptAssemblyInspector", () => {
  it("renders a collapsed sanitized assembly summary without prompt bodies", () => {
    const html = renderToStaticMarkup(
      <ChatPromptAssemblyInspector lang="zh" snapshot={snapshot} />,
    );

    expect(html).toContain("<details");
    expect(html).not.toContain("<details open");
    expect(html).toContain("Prompt 装配");
    expect(html).toContain("session_snapshot_v2");
    expect(html).toContain("128 / 512 tokens");
    expect(html).toContain("core_common");
    expect(html).toContain("agent_role_prompt");
    expect(html).toContain("完整");
    expect(html).toContain("已截断");
    expect(html).not.toContain("不得泄漏的正文");
  });

  it("identifies legacy snapshots without reconstructing their prompt", () => {
    const html = renderToStaticMarkup(
      <ChatPromptAssemblyInspector
        lang="zh"
        snapshot={{ schemaVersion: 2, promptTemplateId: "prompt-chat-default" }}
      />,
    );

    expect(html).toContain("旧快照");
    expect(html).toContain("未记录装配清单");
  });

  it("prefers the last runtime assembly manifest over the frozen session snapshot", () => {
    const runtimeManifest: SessionPromptAssemblyManifest = {
      schemaVersion: 1,
      assemblyMode: "turn_runtime_v2",
      modelProtocol: "basic_chat_no_tools",
      totalEstimatedTokens: 2922,
      segments: [],
    };

    const html = renderToStaticMarkup(
      <ChatPromptAssemblyInspector
        lang="en"
        snapshot={snapshot}
        manifest={runtimeManifest}
      />,
    );

    expect(html).toContain("turn_runtime_v2");
    expect(html).toContain("basic_chat_no_tools");
    expect(html).toContain("2922 /");
    expect(html).not.toContain("openai_chat");
  });
});
