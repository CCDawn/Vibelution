/**
 * Extract experiment + research-loop mutations from TeamsRoute into useTeamExperimentLoopMutations.
 * Usage (from web/): node scripts/extract-experiment-loop-mutations.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/TeamsRoute.tsx";
const outPath = "src/routes/teams/useTeamExperimentLoopMutations.ts";
const src = readFileSync(routePath, "utf8");

const start = src.indexOf("  const createExperimentPlanMutation = useMutation({");
const end = src.indexOf("  const recordSourceCollectionOutputMutation = useMutation({");
if (start < 0 || end <= start) {
  console.error("markers not found", start, end);
  process.exit(1);
}

let body = src.slice(start, end);
body = body
  .replaceAll("sourceCollectionOwnerAgentId", "options.sourceCollectionOwnerAgentId")
  .replaceAll("sourceCollectionIngestorAgentId", "options.sourceCollectionIngestorAgentId")
  .replaceAll("sourceCollectionDraft.goal", "options.sourceCollectionDraftGoal")
  .replaceAll(
    "experimentPlanningStatus?.latestExperimentRound?.stageRoundId || \"\"",
    "options.latestExperimentStageRoundId",
  )
  .replaceAll(
    "experimentPlanningStatus?.latestExperimentRound?.stageRoundId",
    "options.latestExperimentStageRoundId",
  )
  .replaceAll("setExperimentSmokeResultDraft", "options.setExperimentSmokeResultDraft")
  .replaceAll("setExperimentFullRunResultDraft", "options.setExperimentFullRunResultDraft")
  .replaceAll("setExperimentKnowledgeIngestionDraft", "options.setExperimentKnowledgeIngestionDraft")
  .replaceAll("setResearchLoopEvidenceDraft", "options.setResearchLoopEvidenceDraft")
  .replaceAll("setResearchLoopDecisionDraft", "options.setResearchLoopDecisionDraft");

const header = `/**
 * Experiment planning + research-loop write mutations for Teams.
 * EventSource-free; Route remains the draft/view orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type { ExperimentPlanMethodRequest } from "../TeamExperimentMethodPanel";
import {
  experimentPlanningStatusQueryKey,
  researchLoopStatusQueryKey,
  type ExperimentBaselineArtifactDraft,
  type ExperimentBaselineArtifactRegisterPayload,
  type ExperimentDesignFreezePayload,
  type ExperimentFullRunResultDraft,
  type ExperimentFullRunResultRegisterPayload,
  type ExperimentKnowledgeIngestionDraft,
  type ExperimentPlanCreatePayload,
  type ExperimentPlanRecord,
  type ExperimentResultKnowledgeIngestionPayload,
  type ExperimentSmokeResultDraft,
  type ExperimentSmokeResultRegisterPayload,
  type ResearchLoopCreateDraft,
  type ResearchLoopCreatePayload,
  type ResearchLoopDecisionDraft,
  type ResearchLoopDecisionPayload,
  type ResearchLoopEvidenceDraft,
  type ResearchLoopEvidencePayload,
  type ResearchLoopRecord,
} from "./experimentLoopModel";
import { splitDraftList } from "./source-collection/presentationModel";
import { researchStageRoundStatusQueryKey } from "./useResearchWorkflowResources";

export type UseTeamExperimentLoopMutationsOptions = {
  sourceCollectionOwnerAgentId: string;
  sourceCollectionIngestorAgentId: string;
  sourceCollectionDraftGoal: string;
  latestExperimentStageRoundId: string;
  setExperimentSmokeResultDraft: Dispatch<SetStateAction<ExperimentSmokeResultDraft>>;
  setExperimentFullRunResultDraft: Dispatch<SetStateAction<ExperimentFullRunResultDraft>>;
  setExperimentKnowledgeIngestionDraft: Dispatch<SetStateAction<ExperimentKnowledgeIngestionDraft>>;
  setResearchLoopEvidenceDraft: Dispatch<SetStateAction<ResearchLoopEvidenceDraft>>;
  setResearchLoopDecisionDraft: Dispatch<SetStateAction<ResearchLoopDecisionDraft>>;
};

export function useTeamExperimentLoopMutations(options: UseTeamExperimentLoopMutationsOptions) {
  const queryClient = useQueryClient();

`;

const footer = `
  return {
    createExperimentPlanMutation,
    freezeExperimentDesignMutation,
    registerExperimentBaselineArtifactMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    materializeResearchLoopIterationDesignMutation,
  };
}
`;

writeFileSync(outPath, `${header}${body}${footer}`);
console.log("wrote", outPath);

const hookCall = `  const {
    createExperimentPlanMutation,
    freezeExperimentDesignMutation,
    registerExperimentBaselineArtifactMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    materializeResearchLoopIterationDesignMutation,
  } = useTeamExperimentLoopMutations({
    sourceCollectionOwnerAgentId,
    sourceCollectionIngestorAgentId,
    sourceCollectionDraftGoal: sourceCollectionDraft.goal,
    latestExperimentStageRoundId: experimentPlanningStatusQuery.data?.latestExperimentRound?.stageRoundId || "",
    setExperimentSmokeResultDraft,
    setExperimentFullRunResultDraft,
    setExperimentKnowledgeIngestionDraft,
    setResearchLoopEvidenceDraft,
    setResearchLoopDecisionDraft,
  });

`;

let route = src.slice(0, start) + hookCall + src.slice(end);
if (!route.includes('useTeamExperimentLoopMutations')) {
  console.error("hook call missing");
  process.exit(1);
}
if (!route.includes('from "./teams/useTeamExperimentLoopMutations"')) {
  route = route.replace(
    'import {\n  prefetchTeamsPanelPacks,\n  resolveTeamsPanelPrefetchPacks,\n} from "./teams/teamPanelPrefetch";',
    'import {\n  prefetchTeamsPanelPacks,\n  resolveTeamsPanelPrefetchPacks,\n} from "./teams/teamPanelPrefetch";\nimport { useTeamExperimentLoopMutations } from "./teams/useTeamExperimentLoopMutations";',
  );
}
writeFileSync(routePath, route);
console.log("rewrote TeamsRoute.tsx delta", route.length - src.length);
