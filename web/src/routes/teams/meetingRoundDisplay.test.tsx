/**
 * DigestDraftView: renders structured backend validation errors as
 * user-readable text, never as "[object Object]".
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { MeetingDigestDraft } from "../../api/types/hypothesisFirst";
import { DigestDraftView, MeetingRoundDisplay } from "./meetingRoundDisplay";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function renderDraft(draft: MeetingDigestDraft): HTMLDivElement {
  act(() => {
    root.render(<DigestDraftView draft={draft} />);
  });
  return container;
}

describe("DigestDraftView validation errors", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("renders structured {code, message} errors as readable text without [object Object]", () => {
    renderDraft({
      summary: "本轮结论",
      validationErrors: [
        { code: "missing_action_items", message: "缺少行动项，请补充下一轮要执行的动作" },
        { code: "missing_keywords", message: "证据搜集缺少有效关键词" },
      ],
    });
    const list = container.querySelector('[data-testid="meeting-digest-validation-errors"]');
    expect(list).toBeTruthy();
    expect(list?.textContent).toContain("结果校验（2）");
    expect(list?.textContent).toContain("缺少行动项，请补充下一轮要执行的动作");
    expect(list?.textContent).toContain("证据搜集缺少有效关键词");
    expect(container.textContent).not.toContain("[object Object]");
    expect(container.textContent).not.toContain("missing_action_items");
  });

  it("falls back to human-readable copy when message is empty, and omits the card when there are no errors", () => {
    renderDraft({
      summary: "空",
      validationErrors: [{ code: "missing_agreements", message: "  " }],
    });
    const list = container.querySelector('[data-testid="meeting-digest-validation-errors"]');
    expect(list?.textContent).toContain("整理结果校验失败，请重新整理");
    expect(list?.textContent).not.toContain("missing_agreements");

    renderDraft({ summary: "无错误" });
    expect(container.querySelector('[data-testid="meeting-digest-validation-errors"]')).toBeNull();
  });

  it("keeps technical ids behind run details in compact task mode", () => {
    act(() => {
      root.render(
        <MeetingRoundDisplay
          compact
          messages={[]}
          round={{
            program: "p",
            theme: "t",
            campaign: "c",
            question: "Q-01",
            branch: "b",
            workflow: "w",
            agentId: "a",
            schemaVersion: 1,
            meetingRoundId: "meeting-1",
            meetingType: "hypothesis_candidate_generation",
            mode: "generation",
            scopeHash: "scope",
            participants: ["agent-1"],
            status: "closed",
            startedAt: "2026-08-19T01:00:00Z",
            linkedChatRoomId: "room-1",
          }}
        />,
      );
    });
    const headingCopy = container.querySelector("h3")?.parentElement?.textContent;
    expect(headingCopy).toContain("参与者 1 人");
    expect(headingCopy).not.toContain("meeting-1");
    expect(headingCopy).not.toContain("room-1");
    expect(container.querySelector("details")?.textContent).toContain("运行详情");
    expect(container.textContent).toContain("已结束");
    expect(container.textContent).not.toContain("已关门");
  });

  it("shows spoken 3/9 progress while a review discussion is open", () => {
    act(() => {
      root.render(
        <MeetingRoundDisplay
          compact
          messages={[
            { messageId: "m-1", agentId: "agent-1", status: "completed", content: "a" },
            { messageId: "m-2", agentId: "agent-2", status: "completed", content: "b" },
            { messageId: "m-3", agentId: "agent-3", status: "completed", content: "c" },
          ]}
          round={{
            program: "p",
            theme: "t",
            campaign: "c",
            question: "Q-01",
            branch: "b",
            workflow: "w",
            agentId: "a",
            meetingRoundId: "meeting-1",
            meetingType: "hypothesis_review",
            mode: "review",
            scopeHash: "scope",
            participants: ["agent-1", "agent-2", "agent-3", "agent-4", "agent-5", "agent-6", "agent-7", "agent-8", "agent-9"],
            status: "open",
            startedAt: "2026-08-19T01:00:00Z",
            linkedChatRoomId: "room-1",
          }}
        />,
      );
    });
    expect(container.querySelector('[data-testid="meeting-discussion-progress"]')?.textContent).toBe(
      "已发言 3/9 · 待 A004",
    );
  });
});

describe("MeetingMessageCard failure rendering", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("humanizes failed speech and hides the raw error behind details", () => {
    act(() => {
      root.render(
        <MeetingRoundDisplay
          compact
          messages={[
            {
              messageId: "m-1",
              agentId: "agent-9",
              status: "failed",
              content: "network_error: litellm.InternalServerError: OpenAIException - Connection error.",
            },
          ]}
          round={{
            program: "p",
            theme: "t",
            campaign: "c",
            question: "Q-01",
            branch: "b",
            workflow: "w",
            agentId: "a",
            schemaVersion: 1,
            meetingRoundId: "meeting-1",
            meetingType: "hypothesis_review",
            mode: "generation",
            scopeHash: "scope",
            participants: ["agent-1"],
            status: "open",
            startedAt: "2026-08-19T01:00:00Z",
            linkedChatRoomId: "room-1",
          }}
        />,
      );
    });
    const failedCard = container.querySelector('[data-failed="true"]');
    expect(failedCard).not.toBeNull();
    expect(failedCard?.textContent).toContain("Agent 发言失败 · 模型连接错误");
    const details = failedCard?.querySelector("details");
    expect(details?.textContent).toContain("技术详情");
    expect(failedCard?.textContent).toContain("litellm.InternalServerError");
  });

  it("keeps completed speech rendered as-is", () => {
    act(() => {
      root.render(
        <MeetingRoundDisplay
          compact
          messages={[
            {
              messageId: "m-2",
              agentId: "agent-1",
              status: "completed",
              content: "本轮评审确认 cand-a 机制证据最完整。",
            },
          ]}
          round={{
            program: "p",
            theme: "t",
            campaign: "c",
            question: "Q-01",
            branch: "b",
            workflow: "w",
            agentId: "a",
            schemaVersion: 1,
            meetingRoundId: "meeting-1",
            meetingType: "hypothesis_review",
            mode: "generation",
            scopeHash: "scope",
            participants: ["agent-1"],
            status: "open",
            startedAt: "2026-08-19T01:00:00Z",
            linkedChatRoomId: "room-1",
          }}
        />,
      );
    });
    expect(container.querySelector('[data-failed="true"]')).toBeNull();
    expect(container.textContent).toContain("本轮评审确认 cand-a 机制证据最完整。");
  });
});

describe("MeetingRoundDisplay compact inspector chrome", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("keeps digest and actions above a collapsed speech list", () => {
    act(() => {
      root.render(
        <MeetingRoundDisplay
          compact
          round={{
            program: "p",
            theme: "t",
            campaign: "c",
            question: "Q-01",
            branch: "b",
            workflow: "w",
            agentId: "a",
            meetingRoundId: "meeting-1",
            meetingType: "hypothesis_review",
            mode: "review",
            scopeHash: "scope",
            participants: ["a", "b", "c"],
            status: "awaiting_approval",
            startedAt: "2026-08-19T01:00:00Z",
            agendaQuestions: ["每个候选的核心机制是什么？"],
            digestDraft: {
              summary: "本轮没有有效搜集关键词",
              agreements: [],
              disagreements: [],
              actionItems: [],
              knowledgeCandidates: [],
            },
          }}
          messages={[
            {
              messageId: "m-ledger",
              agentId: "agent-20260722-220514-082385",
              role: "评审",
              status: "completed",
              content: "确认：本轮评审输入已闭合。\n**分布/密度组** artifactPath（素数计数数据集） metricValue 与 reproductionCommand。",
            },
          ]}
          actions={<button type="button">退回重新整理</button>}
        />,
      );
    });
    const rootEl = container.querySelector('[data-testid="meeting-round-display"]');
    const html = rootEl?.innerHTML ?? "";
    const digestAt = html.indexOf("讨论结论");
    const actionsAt = html.indexOf("退回重新整理");
    const speechesAt = html.indexOf("1 条发言");
    expect(digestAt).toBeGreaterThan(-1);
    expect(actionsAt).toBeGreaterThan(digestAt);
    expect(speechesAt).toBeGreaterThan(actionsAt);
    expect(container.querySelector('[data-testid="meeting-source-messages"]')?.getAttribute("open")).toBeNull();
    expect(container.textContent).not.toContain("更早的");
    expect(container.textContent).not.toContain("agent-20260722-220514-082385");
    expect(container.textContent).toContain("评审");
    expect(container.textContent).toContain("分布/密度组");
    expect(container.textContent).not.toContain("**分布/密度组**");
    expect(html).toContain("line-clamp-2");
    expect(container.textContent).toContain("全文");
  });

  it("renders English meeting chrome without Chinese labels", () => {
    act(() => {
      root.render(
        <MeetingRoundDisplay
          lang="en"
          compact
          round={{
            program: "p",
            theme: "t",
            campaign: "c",
            question: "Q-01",
            branch: "b",
            workflow: "w",
            agentId: "a",
            meetingRoundId: "meeting-1",
            meetingType: "hypothesis_review",
            mode: "review",
            scopeHash: "scope",
            participants: ["a"],
            status: "closed",
            startedAt: "2026-08-19T01:00:00Z",
            linkedChatRoomId: "room-1",
          }}
          messages={[]}
        />,
      );
    });

    expect(container.textContent).toContain("Review discussion");
    expect(container.textContent).toContain("No discussion messages in this room yet.");
    expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("renders unstructured speech summaries without claiming marker consensus", () => {
    renderDraft({
      summary: "从自由格式发言生成摘要条目",
      agreements: [
        {
          text: "hyp-a 的机制更完整",
          derivedFrom: "unstructured",
          sourceMessageRefs: ["room-1/round-1/msg-1"],
        },
      ],
    });
    expect(container.textContent).toContain("发言摘要：hyp-a 的机制更完整");
    expect(container.textContent).not.toContain("[object Object]");
  });
});
