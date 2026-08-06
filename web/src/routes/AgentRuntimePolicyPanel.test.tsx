import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AgentDelegationPolicy, AgentSupervisionPolicy } from "../api/types";
import { AgentRuntimePolicyPanel } from "./AgentRuntimePolicyPanel";

describe("AgentRuntimePolicyPanel", () => {
  it("keeps policy controls visible while moving communication counts into a focusable tooltip", () => {
    const markup = renderToStaticMarkup(
      <AgentRuntimePolicyPanel
        copy={{
          allowedContextModes: "上下文模式",
          allowSubagents: "允许子 Agent",
          allowWakeMessages: "允许唤醒消息",
          communication: "通信",
          context: "上下文",
          delegation: "委派",
          delegationPolicyTitle: "委派策略",
          evidenceLevel: "证据等级",
          maxConcurrent: "最大并发",
          maxDepth: "最大深度",
          requiresReview: "需要复核",
          resetConfig: "重置",
          reviewMode: "复核模式",
          saveRuntimePolicy: "保存",
          savingRuntimePolicy: "保存中",
          supervisionEnabled: "启用监督",
          supervisionPolicyTitle: "监督策略",
        }}
        lang="zh"
        roleLabel="实验 Agent"
        dirtyLabel="待保存"
        cleanLabel="已保存"
        isDirty={false}
        isPending={false}
        canSave
        notice={{ tone: "success", text: "保存成功" }}
        delegationPolicyDraft={{ allowSubagents: true, allowWakeMessages: false, allowedContextModes: ["isolated"], maxConcurrent: 2, maxDepth: 1 } as AgentDelegationPolicy}
        supervisionPolicyDraft={{ supervisionEnabled: true, requiresReview: false, reviewMode: "advisory", evidenceLevel: "standard" } as AgentSupervisionPolicy}
        inboxPendingCount={2}
        groupContextEventCount={4}
        onUpdateDelegationPolicy={() => undefined}
        onToggleDelegationContextMode={() => undefined}
        onMaxConcurrentChange={() => undefined}
        onMaxDepthChange={() => undefined}
        onUpdateSupervisionPolicy={() => undefined}
        onReset={() => undefined}
        onSave={() => undefined}
      />,
    );

    expect(markup).toContain("委派策略");
    expect(markup).toContain("监督策略");
    expect(markup).toContain("保存成功");
    expect(markup).toContain('tabindex="0"');
    expect(markup).not.toContain(">通信: 2 pending<");
    expect(markup).not.toContain("state-success");
  });
});
