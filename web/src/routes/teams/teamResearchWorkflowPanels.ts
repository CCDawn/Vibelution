/**
 * Research workflow inspector UI pack — panel=-driven and node-driven
 * inspector leaves of the process canvas workspace.
 *
 * Loaded when the research process canvas surface (view === "workflow") is
 * active; the canvas shell itself stays eager.
 *
 * Experiment ledger/status and AI-search packs are separate (U4).
 */

export { ChallengeQuestionDetailPanel } from "./challenge-cup/ChallengeQuestionDetailPanel";
export { ChallengeMvpProgressPanel } from "./research-workflow/ChallengeMvpProgressPanel";
export { EvidenceGraphView } from "./research-workflow/EvidenceGraphView";
export { HypothesisFirstNodeInspector } from "./research-workflow/HypothesisFirstNodeInspector";
export { HypothesisLeaderboardPanel } from "./research-workflow/HypothesisLeaderboardPanel";
export { ResearchAgentBindingPanel } from "./research-workflow/ResearchAgentBindingPanel";
export { ResearchAnomalyInboxPanel } from "./research-workflow/ResearchAnomalyInboxPanel";
export { ResearchProcessDefinitionNodePanel } from "./research-workflow/ResearchProcessDefinitionNodePanel";
export { ResearchProcessNodeInspector } from "./research-workflow/ResearchProcessNodeInspector";
export { ResearchRunLaunchPanel } from "./research-workflow/ResearchRunLaunchPanel";
export { ResearchRunTimeline } from "./research-workflow/ResearchRunTimeline";
export { ResearchTeamPanel } from "./research-workflow/ResearchTeamPanel";
