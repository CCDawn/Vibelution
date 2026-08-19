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
});
