import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

const agentCreateSource = readFileSync(join(here, "agent-create/AgentCreateWizardDialog.tsx"), "utf8");
const agentConfigSource = readFileSync(join(here, "agents/useAgentConfigDraftMutations.ts"), "utf8");
const agentWorkbenchSource = readFileSync(join(here, "agents/useAgentWorkbenchMutations.ts"), "utf8");
const memoryItemSource = readFileSync(join(here, "memory/useMemoryItemMutations.ts"), "utf8");
const teamShellSource = readFileSync(join(here, "teams/useTeamShellMutations.ts"), "utf8");
const memoryKnowledgeSource = readFileSync(join(here, "memory/useMemoryKnowledgeMutations.ts"), "utf8");
const researchProjectSource = readFileSync(join(here, "teams/research-projects/ResearchProjectSwitcher.tsx"), "utf8");
const chatWorkbenchSource = readFileSync(join(here, "chat/ChatCodingRouteWorkbench.tsx"), "utf8");
const chatArchiveQueueSource = readFileSync(join(here, "chat/useChatAgentArchiveQueue.ts"), "utf8");
const challengeCupTelemetrySource = readFileSync(join(here, "teams/challengeCupTelemetry.ts"), "utf8");
const challengeReviewFormSource = readFileSync(join(here, "teams/challenge-cup/ChallengeQuestionReviewForm.tsx"), "utf8");
const challengeRegisterDialogSource = readFileSync(join(here, "teams/challenge-cup/ChallengeQuestionRegisterDialog.tsx"), "utf8");
const challengeRunResetDialogSource = readFileSync(join(here, "teams/challenge-cup/ChallengeQuestionRunResetDialog.tsx"), "utf8");
const hypothesisSelectionListSource = readFileSync(join(here, "teams/challenge-cup/HypothesisSelectionList.tsx"), "utf8");
const hypothesisSelectionPanelSource = readFileSync(join(here, "teams/challenge-cup/HypothesisSelectionPanel.tsx"), "utf8");
const challengeCatalogOverviewSource = readFileSync(join(here, "teams/challenge-cup/ChallengeCatalogOverview.tsx"), "utf8");
const researchRunLaunchPanelSource = readFileSync(join(here, "teams/research-workflow/ResearchRunLaunchPanel.tsx"), "utf8");
const challengeRealBatchPanelSource = readFileSync(join(here, "teams/research-workflow/ChallengeRealBatchControlPanel.tsx"), "utf8");
const challengeMvpProgressPanelSource = readFileSync(join(here, "teams/research-workflow/ChallengeMvpProgressPanel.tsx"), "utf8");
const researchWorkflowCommandsSource = readFileSync(join(here, "teams/research-workflow/useResearchWorkflowCommands.ts"), "utf8");
const researchWorkflowRunSource = readFileSync(join(here, "teams/research-workflow/useResearchWorkflowRun.ts"), "utf8");
const researchWorkflowEventStreamSource = readFileSync(join(here, "teams/research-workflow/useResearchWorkflowEventStream.ts"), "utf8");
const researchWorkflowEventReplaySource = readFileSync(join(here, "teams/research-workflow/useResearchWorkflowEventReplay.ts"), "utf8");

describe("domain user-action telemetry contract", () => {
  it("tracks agent lifecycle mutations", () => {
    expect(agentCreateSource).toContain('startUserAction("agent_create"');
    expect(agentConfigSource).toContain('startUserAction("agent_update"');
    expect(agentWorkbenchSource).toContain('startUserAction("agent_archive"');
    expect(agentWorkbenchSource).toContain('startUserAction("agent_purge"');
    expect(chatWorkbenchSource).toContain('startUserAction("agent_rename"');
    expect(chatArchiveQueueSource).toContain('startUserAction("agent_archive"');
  });

  it("tracks memory item and cleanup mutations", () => {
    expect(memoryItemSource).toContain('"memory_item_create"');
    expect(memoryItemSource).toContain('"memory_item_update"');
    expect(memoryItemSource).toContain('startUserAction("memory_item_delete"');
    expect(memoryItemSource).toContain('startUserAction("memory_item_restore"');
    expect(memoryItemSource).toContain('startUserAction("memory_cleanup_execute"');
  });

  it("tracks team shell mutations", () => {
    expect(teamShellSource).toContain('startUserAction("team_archive"');
    expect(teamShellSource).toContain('startUserAction("team_canvas_save"');
    expect(teamShellSource).toContain('startUserAction("team_message_send"');
    expect(teamShellSource).toContain('startUserAction("team_message_revoke"');
    expect(teamShellSource).toContain("observeChallengeTeamAgentsAutoRepair(");
  });

  it("tracks tier-2 knowledge and research project mutations", () => {
    expect(memoryKnowledgeSource).toContain('startUserAction("memory_knowledge_proposal_create"');
    expect(memoryKnowledgeSource).toContain('startUserAction("memory_knowledge_proposal_review"');
    expect(researchProjectSource).toContain('startUserAction("team_research_project_create"');
    expect(researchProjectSource).toContain('startUserAction("team_research_project_update"');
    expect(researchProjectSource).toContain('startUserAction("team_research_project_activate"');
  });

  it("keeps challenge-cup action literals in the domain telemetry module only", () => {
    const actions = [
      "challenge_question_review_submit",
      "challenge_question_register_submit",
      "challenge_question_publish_submit",
      "challenge_question_run_reset",
      "challenge_hypothesis_selection_record",
      "challenge_hypothesis_candidate_generation_open",
      "challenge_research_run_create",
      "challenge_experiment_activation",
      "challenge_real_batch_authorize",
      "challenge_real_batch_start",
      "challenge_real_batch_cancel",
      "challenge_dev_readiness_run",
      "challenge_dev_batch_run",
      "challenge_workflow_human_gate_resolve",
      "challenge_workflow_offer_submit",
    ];
    for (const action of actions) {
      expect(challengeCupTelemetrySource).toContain(`"${action}"`);
    }
    const observations = [
      "challenge_workflow_stream_interrupted",
      "challenge_workflow_stream_reconnected",
      "challenge_workflow_stream_frame_invalid",
      "challenge_workflow_replay_resync",
      "challenge_workflow_replay_failed",
      "challenge_real_batch_poll_loop_stopped",
      "challenge_real_batch_authorize_shape_invalid",
      "challenge_question_output_schema_rejected",
      "challenge_real_batch_phase_changed",
      "challenge_catalog_active_work_changed",
      "challenge_hypothesis_legacy_fallback",
      "challenge_team_agents_auto_repair",
    ];
    for (const code of observations) {
      expect(challengeCupTelemetrySource).toContain(`"${code}"`);
    }
  });

  it("wires challenge-cup question review, register, and reset surfaces", () => {
    expect(challengeReviewFormSource).toContain("trackQuestionReviewSubmit(");
    expect(challengeRegisterDialogSource).toContain("trackQuestionRegisterSubmit(");
    expect(challengeRegisterDialogSource).toContain("trackQuestionPublishSubmit(");
    expect(challengeRegisterDialogSource).toContain("observeQuestionOutputSchemaRejected(");
    expect(challengeRunResetDialogSource).toContain("trackQuestionRunReset(");
  });

  it("wires challenge-cup hypothesis selection and catalog overview surfaces", () => {
    expect(hypothesisSelectionListSource).toContain("trackHypothesisSelectionRecord(");
    expect(hypothesisSelectionListSource).toContain("observeHypothesisLegacyFallback(");
    expect(hypothesisSelectionPanelSource).toContain("trackHypothesisCandidateGenerationOpen(");
    expect(challengeCatalogOverviewSource).toContain("trackDevBatchRun(");
    expect(challengeCatalogOverviewSource).toContain("observeCatalogActiveWorkChanged(");
  });

  it("wires challenge-cup run launch, real batch, and dev control surfaces", () => {
    expect(researchRunLaunchPanelSource).toContain("trackExperimentActivation(");
    expect(challengeRealBatchPanelSource).toContain("trackRealBatchAuthorize(");
    expect(challengeRealBatchPanelSource).toContain("trackRealBatchStart(");
    expect(challengeRealBatchPanelSource).toContain("trackRealBatchCancel(");
    expect(challengeRealBatchPanelSource).toContain("observeRealBatchAuthorizeShapeInvalid(");
    expect(challengeRealBatchPanelSource).toContain("observeRealBatchPollLoopStopped(");
    expect(challengeRealBatchPanelSource).toContain("observeRealBatchPhaseChanged(");
    expect(challengeMvpProgressPanelSource).toContain("trackDevReadinessRun(");
    expect(challengeMvpProgressPanelSource).toContain("trackDevBatchRun(");
  });

  it("wires challenge-cup workflow run, human gate, and stream anomaly surfaces", () => {
    expect(researchWorkflowCommandsSource).toContain("trackResearchRunCreate(");
    expect(researchWorkflowCommandsSource).toContain("trackWorkflowOfferSubmit(");
    expect(researchWorkflowRunSource).toContain("trackWorkflowHumanGateResolve(");
    expect(researchWorkflowEventStreamSource).toContain("observeWorkflowStreamInterrupted(");
    expect(researchWorkflowEventStreamSource).toContain("observeWorkflowStreamReconnected(");
    expect(researchWorkflowEventStreamSource).toContain("observeWorkflowStreamFrameInvalid(");
    expect(researchWorkflowEventReplaySource).toContain("observeWorkflowReplayResync(");
    expect(researchWorkflowEventReplaySource).toContain("observeWorkflowReplayFailed(");
  });
});
