/**
 * Wave 8P: promote SC mutation payload types + extract useTeamSourceCollectionMutations.
 * Usage (from web/): node scripts/extract-source-collection-mutations-v2.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/TeamsRoute.tsx";
const modelPath = "src/routes/teams/sourceCollectionMutationModel.ts";
const hookPath = "src/routes/teams/useTeamSourceCollectionMutations.ts";
const src = readFileSync(routePath, "utf8");

function sliceType(name) {
  const start = src.indexOf(`type ${name} = `);
  if (start < 0) throw new Error(`type not found: ${name}`);
  // find matching end by brace depth from first { or ;
  let i = start + `type ${name} = `.length;
  while (i < src.length && /\s/.test(src[i])) i++;
  if (src[i] !== "{") {
    // could be simple type - find semicolon
    const end = src.indexOf(";", i);
    return src.slice(start, end + 1);
  }
  let depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    if (src[i] === "}") {
      depth--;
      if (depth === 0) {
        // include trailing ;
        let j = i + 1;
        while (j < src.length && src[j] !== ";") j++;
        return src.slice(start, j + 1);
      }
    }
  }
  throw new Error(`unclosed type ${name}`);
}

const typeNames = [
  "TeamWorkflowKnowledgeIngestionPrecheckPayload",
  "SourceCollectionOutputDraft",
  "TeamWorkflowSourceCollectionStorageOpenPayload",
  "SourceCollectionSearchExecutionEvent",
  "TeamWorkflowSourceCollectionSearchExecutionPayload",
  "TeamWorkflowPaperNoteChunkPlanPayload",
  "TeamWorkflowSourceQualityAssessmentPayload",
  "TeamWorkflowSourceQualityBatchAssessmentPayload",
];

const typeBlocks = typeNames.map((n) => sliceType(n));
// export each type
const exportedTypes = typeBlocks.map((block) => block.replace(/^type /, "export type ")).join("\n\n");

const model = `/**
 * Source-collection mutation payload types shared by TeamsRoute and write hooks.
 * Promoted out of TeamsRoute to unlock EventSource-free mutation extraction.
 */
import type {
  DataProcessingCollectionOutputPayload,
  DataProcessingStatus,
  TeamWorkflowCandidate,
  TeamWorkflowKnowledgeIngestionStatus,
  TeamWorkflowOrchestration,
  TeamWorkflowSourceCollectionRunStartPayload,
  TeamWorkflowSourceQualityStatus,
  TeamWorkflowDataRecordSourceCandidateImportPayload,
} from "../../api/types";
import type { SourceCollectionStorageArtifacts, SourceCollectionStorageOpenTarget } from "./source-collection/presentationModel";

${exportedTypes}
`;

writeFileSync(modelPath, model);
console.log("wrote model", modelPath);

// Extract mutation body
const mutStart = src.indexOf("  const recordSourceCollectionOutputMutation = useMutation({");
const mutEnd = src.indexOf("  const canvasSavePendingForTeam = (teamId: string | undefined | null) =>");
if (mutStart < 0 || mutEnd <= mutStart) {
  console.error("mutation markers", mutStart, mutEnd);
  process.exit(1);
}
let body = src.slice(mutStart, mutEnd);
body = body
  .replaceAll("sourceCollectionOwnerAgentId", "options.sourceCollectionOwnerAgentId")
  .replaceAll("sourceCollectionExtractorAgentId", "options.sourceCollectionExtractorAgentId")
  .replaceAll("sourceCollectionRelationMapperAgentId", "options.sourceCollectionRelationMapperAgentId")
  .replaceAll("setSelectedSourceCollectionRunId", "options.setSelectedSourceCollectionRunId")
  .replaceAll("setSourceCollectionOutputDraft", "options.setSourceCollectionOutputDraft")
  .replaceAll("scrollSourceCollectionPanelIntoView", "options.scrollSourceCollectionPanelIntoView")
  .replaceAll("sourceCollectionDraft.topic", "options.sourceCollectionDraftTopic")
  .replaceAll("sourceCollectionDraft.maxResultsPerQuery", "options.sourceCollectionDraftMaxResultsPerQuery");

const hook = `/**
 * Source-collection write mutations for Teams (search/extract/quality/graph/ingestion).
 * EventSource-free; Route remains draft/view/session-task orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  DataProcessingCollectionAssignmentListPayload,
  DataProcessingCollectionOutputPayload,
  TeamWorkflowCandidateGraphBuildPayload,
  TeamWorkflowDataRecordSourceCandidateImportPayload,
  TeamWorkflowKnowledgeCollectionIngestionPayload,
  TeamWorkflowSourceCollectionExtractionPayload,
} from "../../api/types";
import { SOURCE_COLLECTION_RUN_PREVIEW_LIMIT } from "./source-collection/presentationModel";
import type { SourceCollectionStorageOpenTarget } from "./source-collection/presentationModel";
import {
  sourceCollectionRunRecordsQueryKey,
  sourceCollectionSummaryQueryPrefix,
} from "./teamWorkflowQueryKeys";
import {
  paperNoteChunkStatusQueryKey,
  researchStageRoundStatusQueryKey,
  sourceQualityStatusQueryKey,
  TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT,
} from "./useResearchWorkflowResources";
import type {
  SourceCollectionOutputDraft,
  TeamWorkflowKnowledgeIngestionPrecheckPayload,
  TeamWorkflowPaperNoteChunkPlanPayload,
  TeamWorkflowSourceCollectionSearchExecutionPayload,
  TeamWorkflowSourceCollectionStorageOpenPayload,
  TeamWorkflowSourceQualityAssessmentPayload,
  TeamWorkflowSourceQualityBatchAssessmentPayload,
} from "./sourceCollectionMutationModel";

export type UseTeamSourceCollectionMutationsOptions = {
  sourceCollectionOwnerAgentId: string;
  sourceCollectionExtractorAgentId: string;
  sourceCollectionRelationMapperAgentId: string;
  sourceCollectionDraftTopic: string;
  sourceCollectionDraftMaxResultsPerQuery: number;
  setSelectedSourceCollectionRunId: Dispatch<SetStateAction<string>>;
  setSourceCollectionOutputDraft: Dispatch<SetStateAction<SourceCollectionOutputDraft>>;
  scrollSourceCollectionPanelIntoView: (panelId: string) => void;
};

export function useTeamSourceCollectionMutations(options: UseTeamSourceCollectionMutationsOptions) {
  const queryClient = useQueryClient();

${body}
  return {
    recordSourceCollectionOutputMutation,
    executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorageMutation,
    assessSourceQualityMutation,
    assessSourceQualityBatchMutation,
    planPaperNoteChunksMutation,
    buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletionMutation,
  };
}
`;

writeFileSync(hookPath, hook);
console.log("wrote hook", hookPath);

// Remove type blocks from route (from first type to last, carefully)
// Replace types with imports and mutations with hook call
let route = src;

// Insert imports after teamPanelPrefetch / experiment loop imports
if (!route.includes("./teams/sourceCollectionMutationModel")) {
  route = route.replace(
    'import { useTeamExperimentLoopMutations } from "./teams/useTeamExperimentLoopMutations";',
    `import { useTeamExperimentLoopMutations } from "./teams/useTeamExperimentLoopMutations";
import { useTeamSourceCollectionMutations } from "./teams/useTeamSourceCollectionMutations";
import type {
  SourceCollectionOutputDraft,
  TeamWorkflowKnowledgeIngestionPrecheckPayload,
  TeamWorkflowPaperNoteChunkPlanPayload,
  TeamWorkflowSourceCollectionSearchExecutionPayload,
  TeamWorkflowSourceCollectionStorageOpenPayload,
  TeamWorkflowSourceQualityAssessmentPayload,
  TeamWorkflowSourceQualityBatchAssessmentPayload,
  SourceCollectionSearchExecutionEvent,
} from "./teams/sourceCollectionMutationModel";`,
  );
}

// Remove local type definitions
for (const name of typeNames) {
  const block = sliceType(name);
  // also remove blank lines around - use exact block from original src
  const idx = route.indexOf(block);
  if (idx < 0) {
    // try without export difference - block from original
    const orig = typeBlocks[typeNames.indexOf(name)];
    const oidx = route.indexOf(orig);
    if (oidx < 0) {
      console.warn("could not remove type", name);
      continue;
    }
    route = route.slice(0, oidx) + route.slice(oidx + orig.length);
  } else {
    route = route.slice(0, idx) + route.slice(idx + block.length);
  }
}
// clean extra blank lines (max 2)
route = route.replace(/\n{3,}/g, "\n\n");

// Replace mutation block
const newMutStart = route.indexOf("  const recordSourceCollectionOutputMutation = useMutation({");
const newMutEnd = route.indexOf("  const canvasSavePendingForTeam = (teamId: string | undefined | null) =>");
if (newMutStart < 0 || newMutEnd <= newMutStart) {
  console.error("route mutation markers after type strip", newMutStart, newMutEnd);
  process.exit(1);
}

const hookCall = `  const {
    recordSourceCollectionOutputMutation,
    executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorageMutation,
    assessSourceQualityMutation,
    assessSourceQualityBatchMutation,
    planPaperNoteChunksMutation,
    buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletionMutation,
  } = useTeamSourceCollectionMutations({
    sourceCollectionOwnerAgentId,
    sourceCollectionExtractorAgentId,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionDraftTopic: sourceCollectionDraft.topic,
    sourceCollectionDraftMaxResultsPerQuery: sourceCollectionDraft.maxResultsPerQuery || 3,
    setSelectedSourceCollectionRunId,
    setSourceCollectionOutputDraft,
    scrollSourceCollectionPanelIntoView,
  });

`;

// Problem: scrollSourceCollectionPanelIntoView is defined AFTER mutations currently.
// Check order after extract.
const scrollIdx = route.indexOf("const scrollSourceCollectionPanelIntoView");
console.log("scroll function at", scrollIdx, "mutation at", newMutStart, "scroll before mutations?", scrollIdx > 0 && scrollIdx < newMutStart);

route = route.slice(0, newMutStart) + hookCall + route.slice(newMutEnd);
writeFileSync(routePath, route);
console.log("rewrote route", "delta", route.length - src.length);
console.log("scroll still after hook call?", route.indexOf("scrollSourceCollectionPanelIntoView") > route.indexOf("useTeamSourceCollectionMutations({"));
