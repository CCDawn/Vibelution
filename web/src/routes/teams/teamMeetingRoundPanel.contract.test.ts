import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const panelSource = readFileSync(
  new URL("./TeamMeetingRoundPanel.tsx", import.meta.url),
  "utf8",
);
const displaySource = readFileSync(
  new URL("./meetingRoundDisplay.tsx", import.meta.url),
  "utf8",
);
const timelineSource = readFileSync(
  new URL("./TeamHypothesisRoundTimeline.tsx", import.meta.url),
  "utf8",
);
const detailPanelSource = readFileSync(
  new URL("./challenge-cup/ChallengeQuestionDetailPanel.tsx", import.meta.url),
  "utf8",
);

describe("TeamMeetingRoundPanel contract (HF-6)", () => {
  it("uses named hypothesisFirst API functions and never raw paths", () => {
    expect(panelSource).toContain("fetchMeetingRound");
    expect(panelSource).toContain("fetchMeetingRoundSourceMessages");
    expect(panelSource).toContain("generationMeeting");
    expect(panelSource).not.toContain("closeHypothesisReviewMeeting");
    expect(panelSource).toContain("queryKeys.teamMeetingRound(");
    expect(panelSource).not.toMatch(/(?<![\w.])fetch\(/);
    expect(panelSource).not.toMatch(/["'`]\/api\//);
    expect(panelSource).not.toContain("workflow-orchestration/meeting-rounds");
  });

  it("renders room discussion messages and the closure digest artifact", () => {
    expect(displaySource).toContain("meeting-source-messages");
    expect(displaySource).toContain("meeting-digest-draft");
    expect(displaySource).toContain("agreements");
    expect(displaySource).toContain("disagreements");
    expect(displaySource).toContain("actionItems");
    expect(displaySource).toContain("knowledgeCandidates");
    expect(displaySource).toContain("decisionRefs");
    expect(displaySource).toContain("evidenceRequests");
    expect(displaySource).toContain("条发言");
    expect(displaySource).toContain("meetingSpeakerLabel");
    expect(displaySource).not.toContain("更早的");
  });

  it("derives the four-state status from the server projection only", () => {
    expect(displaySource).toContain("round.status");
    expect(displaySource).toContain('"open"');
    expect(displaySource).toContain('"summarizing"');
    expect(displaySource).toContain('"awaiting_approval"');
    expect(displaySource).toContain('"closed"');
    expect(displaySource).toContain("VStatusChip");
  });

  it("keeps the archive panel read-only without early-close writes", () => {
    expect(panelSource).not.toContain("人工确认关门");
    expect(panelSource).not.toContain("closeMutation");
    expect(panelSource).not.toContain("select_candidate");
    expect(panelSource).not.toContain("beginMeetingSummary");
    expect(panelSource).not.toContain("submitMeetingDigestDraft");
  });

  it("stays on the VUI product API surface", () => {
    expect(panelSource).toContain('from "../../components/vui"');
    expect(panelSource).not.toContain("renderers/shadcn");
    expect(panelSource).not.toContain("@heroui");
    expect(timelineSource).toContain('from "../../components/vui"');
    expect(timelineSource).not.toContain("renderers/shadcn");
    expect(timelineSource).not.toContain("@heroui");
  });

  it("mounts the discussion panel and round timeline in the question detail panel", () => {
    expect(detailPanelSource).toContain('from "../TeamMeetingRoundPanel"');
    expect(detailPanelSource).toContain("<TeamMeetingRoundPanel");
    expect(detailPanelSource).toContain('from "../TeamHypothesisRoundTimeline"');
    expect(detailPanelSource).toContain("<TeamHypothesisRoundTimeline");
    expect(detailPanelSource).toContain("hypothesis-first-meeting");
    expect(detailPanelSource).toContain("hypothesis-first-rounds");
  });
});

describe("TeamHypothesisRoundTimeline contract (HF-6)", () => {
  it("uses named hypothesisFirst API functions and never raw paths", () => {
    expect(timelineSource).toContain("fetchHypothesisRounds");
    expect(timelineSource).toContain("queryKeys.teamHypothesisRounds");
    expect(timelineSource).not.toContain("fetch(");
    expect(timelineSource).not.toMatch(/["'`]\/api\//);
  });

  it("renders the lineage chain and seven-dimension scores per round", () => {
    expect(timelineSource).toContain("hypothesis-round-lineage");
    expect(timelineSource).toContain("round.lineage");
    expect(timelineSource).toContain("赛题候选");
    expect(timelineSource).toContain("前轮");
    expect(timelineSource).toContain("candidate.scores");
    expect(timelineSource).toContain("paretoFrontCandidateIds");
    expect(timelineSource).toContain("hypothesis-round-metareview");
  });
});
