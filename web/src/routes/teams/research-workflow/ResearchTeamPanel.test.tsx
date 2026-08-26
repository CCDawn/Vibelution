import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import { ResearchTeamPanel } from "./ResearchTeamPanel";
import type { ScopedDiscussionModel } from "./scopedDiscussionModel";

const scopedDiscussion: ScopedDiscussionModel = {
  status: "ready",
  degradedReason: "",
  scope: {
    version: 1,
    kind: "candidate_review",
    teamId: "research-team",
    researchProjectId: "project-sci-003",
    workflowRunId: "run-sci-003",
    workflowNodeId: "hf_review",
    questionId: "SCI-003",
    selectionId: "selection-sci-003",
    candidateId: "candidate-sci-003",
  },
  scopeHash: "scope-hash-sci-003",
  roomId: "room-sci-003",
  meetingRoundId: "hf-review-sci-003-r1",
  questionId: "SCI-003",
  selectionId: "selection-sci-003",
  candidateId: "candidate-sci-003",
  query: { kind: "room", room: "room-sci-003" },
  search: "?room=room-sci-003",
  deepLink: "/chat?room=room-sci-003&returnTo=%2Fteams%3FteamId%3Dresearch-team%26researchView%3Dworkflow%26workflowId%3Dchallenge-cup-research%26questionId%3DSCI-003%26runId%3Drun-sci-003%26node%3Dhf_review%26panel%3Dnode&meetingRound=hf-review-sci-003-r1",
  returnTo: "/teams?teamId=research-team&researchView=workflow&workflowId=challenge-cup-research&questionId=SCI-003&runId=run-sci-003&node=hf_review&panel=node",
  returnLabel: "返回科研流程",
  selectedRoundId: "round-sci-003-r1",
};

function renderPanel(language: "zh" | "en" = "zh") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.configPublic(), { language });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ResearchTeamPanel
          teamId="research-team"
          teamName="科研团队"
          linkedChatRoomId=""
          run={null}
          projection={null}
          effectiveBindings={null}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ResearchTeamPanel", () => {
  it("mounts the research project switcher on the main-path team panel", () => {
    const html = renderPanel();
    expect(html).toContain("研究项目");
    expect(html).toContain("当前研究项目");
    expect(html).toContain("团队治理");
    expect(html).toContain("绑定覆盖");
    expect(html).toContain("未创建运行");
    expect(html).toContain("团队尚未关联讨论会话");
  });

  it("renders English chrome when the shell language is en", () => {
    const html = renderPanel("en");
    expect(html).toContain("Research projects");
    expect(html).toContain("Current research project");
    expect(html).toContain("Team governance");
    expect(html).toContain("Binding coverage");
    expect(html).toContain("No run yet");
    expect(html).toContain("No chat room is linked to this team yet");
  });

  it("opens team chat with this round meetingRoundId", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ResearchTeamPanel
            teamId="research-team"
            teamName="科研团队"
            linkedChatRoomId="room-1"
            run={null}
            projection={null}
            effectiveBindings={null}
            meetingRoundId="hf-review-1"
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(html).toContain("meetingRound=hf-review-1");
    expect(html).toContain("打开团队讨论");
  });

  it("uses the validated scoped discussion for a selected question and preserves its return context", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ResearchTeamPanel
            teamId="research-team"
            teamName="科研团队"
            linkedChatRoomId="team-room-must-not-be-used"
            run={null}
            projection={null}
            effectiveBindings={null}
            questionId="SCI-003"
            discussionModel={scopedDiscussion}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain("当前题目");
    expect(html).toContain("SCI-003");
    expect(html).toContain("打开本题讨论");
    expect(html).toContain("room-sci-003");
    expect(html).toContain("questionId%3DSCI-003");
    expect(html).toContain("node%3Dhf_review");
    expect(html).not.toContain("team-room-must-not-be-used");
    expect(html).not.toContain("当前研究项目");
    expect(html).not.toContain("新建项目");
  });

  it("fails closed instead of falling back to the team room when the scoped discussion is unavailable", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ResearchTeamPanel
            teamId="research-team"
            teamName="科研团队"
            linkedChatRoomId="team-room-must-not-be-used"
            run={null}
            projection={null}
            effectiveBindings={null}
            questionId="SCI-003"
            discussionModel={{
              ...scopedDiscussion,
              status: "degraded",
              degradedReason: "active_discussion_room_mismatch",
              deepLink: "",
            }}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain("当前题目尚未关联精确讨论会话");
    expect(html).not.toContain("team-room-must-not-be-used");
    expect(html).not.toContain("打开本题讨论");
  });
});
