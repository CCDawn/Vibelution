import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ChatRoomMessage } from "../../api/types";
import { ChatGroupMessageBody } from "./ChatGroupMessagePresentation";
import styles from "./ChatGroupMessagePresentation.styles";

function message(patch: Partial<ChatRoomMessage> = {}): ChatRoomMessage {
  return {
    messageId: "msg-1",
    participantId: "p1",
    sessionId: "s1",
    speakerTitle: "planner",
    status: "completed",
    content: "短回复",
    summary: "",
    timestamp: "2026-08-20T00:00:00Z",
    ...patch,
  };
}

const bodyProps = {
  identityName: "顾言初",
  lang: "zh" as const,
  expandedMessageIds: [] as string[],
  mentionTargets: [],
  onOpenMentionTarget: () => undefined,
  onToggleExpanded: () => undefined,
};

describe("ChatGroupMessageBody", () => {
  it("renders a structured Challenge Cup message as scannable sections", () => {
    const html = renderToStaticMarkup(
      <ChatGroupMessageBody
        {...bodyProps}
        message={message({
          content: "兼容正文不应成为结构化视图的主体。",
          messagePayload: {
            schemaVersion: 1,
            kind: "challenge_meeting_message",
            display: {
              conclusion: "当前证据只能支持间接外推，不能升级候选。",
              sections: [
                {
                  title: "判断依据",
                  bullets: ["Tao 2014 不在目标作用域内。", "Elgindi 2021 只能作为间接支持。"],
                },
              ],
            },
            protocol: {
              agreements: ["现有锚点只能作为间接支持。"],
              disagreements: [
                {
                  issue: "候选是否已经达到升级门槛",
                  positions: ["知识管理 Agent：暂不升级"],
                  unresolvedReason: "缺少直接证据",
                },
              ],
              risks: ["2022 年后的进展尚未覆盖。"],
              actionItems: [],
              knowledgeCandidates: [],
              proposedCandidates: [],
              evidenceRequests: [
                {
                  rationale: "缺少光滑初值真 NS 爆破的直接证据",
                  candidateRefs: ["sci-002-c034eaea9"],
                  searchEnvelope: {
                    keywords: ["smooth initial data", "Navier-Stokes blowup"],
                    sourceTypes: ["paper", "preprint"],
                    evidenceLevels: ["peer_reviewed"],
                  },
                  requirements: { minEvidenceLevel: "medium", completeness: "stage-one" },
                },
              ],
            },
            audit: {
              parseStatus: "structured",
              rawModelOutput: "{\"schemaVersion\":1,\"display\":{},\"protocol\":{}}",
            },
          },
        })}
      />,
    );

    expect(html).toContain("当前证据只能支持间接外推，不能升级候选。");
    expect(html).toContain("判断依据");
    expect(html).toContain("已形成共识");
    expect(html).toContain("仍有分歧");
    expect(html).toContain("需要补证据");
    expect(html).toContain("smooth initial data");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toMatch(/aria-controls="challenge-message-protocol-[^"]+"/);
    expect(html).toMatch(/aria-labelledby="challenge-message-title-[^"]+"/);
    expect(html).not.toContain("兼容正文不应成为结构化视图的主体。");
    expect(html).not.toContain("{&quot;schemaVersion&quot;:1");
  });

  it("reveals the complete raw protocol only when requested", () => {
    const html = renderToStaticMarkup(
      <ChatGroupMessageBody
        {...bodyProps}
        expandedMessageIds={["msg-1:protocol"]}
        message={message({
          messagePayload: {
            schemaVersion: 1,
            kind: "challenge_meeting_message",
            display: { conclusion: "保留当前等级。", sections: [] },
            protocol: {
              agreements: [],
              disagreements: [],
              risks: [],
              actionItems: [],
              knowledgeCandidates: [],
              proposedCandidates: [],
              evidenceRequests: [],
            },
            audit: {
              parseStatus: "structured",
              rawModelOutput: "RAW-PROTOCOL-LAST-LINE",
            },
          },
        })}
      />,
    );

    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain("RAW-PROTOCOL-LAST-LINE");
  });

  it("keeps internal discussion visible instead of hiding the body", () => {
    const html = renderToStaticMarkup(
      <ChatGroupMessageBody
        {...bodyProps}
        message={message({
          audience: "internal",
          visibility: "collapsed_by_default",
          content: "内部讨论仍应能直接读到开头。",
        })}
      />,
    );
    expect(html).toContain("内部讨论仍应能直接读到开头。");
    expect(html).not.toContain("展开全文");
    expect(html).not.toContain(styles.groupBubbleBodyCollapsed);
  });

  it("clamps long speech without using hidden", () => {
    const content = "先看主诉。".repeat(80);
    const html = renderToStaticMarkup(
      <ChatGroupMessageBody
        {...bodyProps}
        message={message({
          audience: "internal",
          visibility: "collapsed_by_default",
          content,
        })}
      />,
    );
    expect(html).toContain("先看主诉。");
    expect(html).toContain("展开全文");
    expect(html).toContain(styles.groupBubbleBodyCollapsed);
    expect(styles.groupBubbleBodyCollapsed).toContain("[-webkit-line-clamp:8]");
    expect(styles.groupBubbleBodyCollapsed).not.toMatch(/(?:^|\s)hidden(?:\s|$)/);
  });
});
