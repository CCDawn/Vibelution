/** @vitest-environment happy-dom */
import React from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentMemoryPolicyPanel } from "./AgentMemoryPolicyPanel";

const copy = {
  addSharedGroup: "添加",
  knowledgeBasePlaceholder: "知识库 ID",
  memoryPolicyTitle: "记忆策略",
  memoryEnabled: "启用个人记忆",
  memoryEnabledHint: "关闭后该 Agent 不再挂载个人记忆写入工具，也不注入历史个人记忆。",
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
};

const baseDraft = {
  enabled: true,
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
};

const baseProps = {
  copy,
  lang: "zh" as const,
  policyId: "memory-policy",
  rootPath: "C:/Users/agent/memory",
  memoryGroupOptions: [] as string[],
  dirty: false,
  pending: false,
  canSave: true,
  onDraftChange: () => undefined,
  onAddMemoryGroup: () => undefined,
  onRemoveMemoryGroup: () => undefined,
  onAddKnowledgeBaseId: () => undefined,
  onRemoveKnowledgeBaseId: () => undefined,
  onOpenMemoryPage: () => undefined,
  onReset: () => undefined,
  onSave: () => undefined,
};

describe("AgentMemoryPolicyPanel", () => {
  it("keeps the editable controls visible while hiding root path and empty helper copy", () => {
    const markup = renderToStaticMarkup(
      <AgentMemoryPolicyPanel
        {...baseProps}
        draft={baseDraft}
      />,
    );

    expect(markup).toContain("memory-policy");
    expect(markup).toContain("记忆策略");
    expect(markup).toContain("知识库权限");
    expect(markup).toContain('data-vui-recipe="settings-form-page"');
    expect(markup).toContain('data-vui="settings-form-footer"');
    expect((markup.match(/data-vui="field-row"/g) ?? []).length).toBe(8);
    expect(markup).toContain("保存");
    expect(markup).toContain('aria-label="重置记忆配置"');
    expect(markup).toContain("启用个人记忆");
    expect(markup).toContain('tabindex="0"');
    expect(markup).not.toContain(">C:/Users/agent/memory<");
    expect(markup).not.toContain(">未配置共享组<");
    expect(markup).not.toContain(">未配置知识库<");
    expect(markup).not.toContain("state-success");
  });

  it("renders the memory switch checked state from the draft", () => {
    const markup = renderToStaticMarkup(
      <AgentMemoryPolicyPanel {...baseProps} draft={{ ...baseDraft, enabled: false }} />,
    );

    expect(markup).toContain('data-selected="false"');
    expect(markup).toContain('data-vui="checkbox"');
  });
});

describe("AgentMemoryPolicyPanel interactions", () => {
  let container: HTMLDivElement | null = null;
  let root: Root | null = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    if (root) {
      flushSync(() => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
  });

  it("reports the toggled enabled value through onDraftChange", () => {
    const onDraftChange = vi.fn();
    flushSync(() => {
      root?.render(
        <AgentMemoryPolicyPanel {...baseProps} draft={baseDraft} onDraftChange={onDraftChange} />,
      );
    });

    const input = container?.querySelector<HTMLInputElement>('input[type="checkbox"]');
    expect(input).not.toBeNull();
    expect(input?.checked).toBe(true);

    flushSync(() => {
      input?.click();
    });

    expect(onDraftChange).toHaveBeenCalledWith({ enabled: false });
  });

  it("keeps the shared-group and knowledge-base ACL add/remove callbacks wired", () => {
    const onAddMemoryGroup = vi.fn();
    const onRemoveMemoryGroup = vi.fn();
    const onAddKnowledgeBaseId = vi.fn();
    const draft = {
      ...baseDraft,
      readSharedGroups: ["research-team"],
      newReadGroup: "project-shared",
      newReadKnowledgeBaseId: "research-kb",
    };
    flushSync(() => {
      root?.render(
        <AgentMemoryPolicyPanel
          {...baseProps}
          draft={draft}
          onAddMemoryGroup={onAddMemoryGroup}
          onRemoveMemoryGroup={onRemoveMemoryGroup}
          onAddKnowledgeBaseId={onAddKnowledgeBaseId}
        />,
      );
    });

    const removeGroupButton = container?.querySelector<HTMLButtonElement>('button[aria-label="移除 research-team"]');
    const knowledgeBaseInput = container?.querySelector<HTMLInputElement>('input[aria-label="读取知识库"]');
    const knowledgeBaseRow = knowledgeBaseInput?.closest('[data-vui="field-row"]');
    const addKnowledgeBaseButton = Array.from(knowledgeBaseRow?.querySelectorAll<HTMLButtonElement>("button") ?? [])
      .find((button) => button.textContent?.trim() === copy.addSharedGroup);

    flushSync(() => {
      removeGroupButton?.click();
      addKnowledgeBaseButton?.click();
    });

    expect(onRemoveMemoryGroup).toHaveBeenCalledWith("readSharedGroups", "research-team");
    expect(onAddKnowledgeBaseId).toHaveBeenCalledWith("readKnowledgeBaseIds", "research-kb");
  });
});
