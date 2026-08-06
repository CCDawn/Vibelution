import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentMemoryPolicyPanel } from "./AgentMemoryPolicyPanel";

describe("AgentMemoryPolicyPanel", () => {
  it("keeps the editable controls visible while hiding root path and empty helper copy", () => {
    const markup = renderToStaticMarkup(
      <AgentMemoryPolicyPanel
        copy={{
          addSharedGroup: "添加",
          knowledgeBasePlaceholder: "知识库 ID",
          memoryPolicyTitle: "记忆策略",
          noKnowledgeBaseIds: "未配置知识库",
          noSharedGroups: "未配置共享组",
          proposeKnowledgeBaseIds: "提议知识库",
          rateKnowledgeBaseIds: "评分知识库",
          readKnowledgeBaseIds: "读取知识库",
          readSharedGroups: "读取共享组",
          resetConfig: "重置",
          reviewKnowledgeBaseIds: "复核知识库",
          saveMemoryPolicy: "保存",
          savingMemoryPolicy: "保存中",
          sharedGroupPlaceholder: "共享组",
          writeSharedGroups: "写入共享组",
        }}
        lang="zh"
        policyId="memory-policy"
        rootPath="C:/Users/agent/memory"
        draft={{
          readSharedGroups: [],
          writeSharedGroups: [],
          readKnowledgeBaseIds: [],
          proposeKnowledgeBaseIds: [],
          reviewKnowledgeBaseIds: [],
          rateKnowledgeBaseIds: [],
          newReadGroup: "",
          newWriteGroup: "",
          newReadKnowledgeBaseId: "",
          newProposeKnowledgeBaseId: "",
          newReviewKnowledgeBaseId: "",
          newRateKnowledgeBaseId: "",
        }}
        memoryGroupOptions={[]}
        dirty={false}
        pending={false}
        canSave
        onDraftChange={() => undefined}
        onAddMemoryGroup={() => undefined}
        onRemoveMemoryGroup={() => undefined}
        onAddKnowledgeBaseId={() => undefined}
        onRemoveKnowledgeBaseId={() => undefined}
        onOpenMemoryPage={() => undefined}
        onReset={() => undefined}
        onSave={() => undefined}
      />,
    );

    expect(markup).toContain("memory-policy");
    expect(markup).toContain("保存");
    expect(markup).toContain('tabindex="0"');
    expect(markup).not.toContain(">C:/Users/agent/memory<");
    expect(markup).not.toContain(">未配置共享组<");
    expect(markup).not.toContain(">未配置知识库<");
    expect(markup).not.toContain("state-success");
  });
});
