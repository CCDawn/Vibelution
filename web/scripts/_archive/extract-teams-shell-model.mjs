/**
 * M5 structure: extract TeamsRoute pure shell helpers into teams/teamRouteShellModel.ts
 * (style-bound helpers stay in the shell)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/TeamsRoute.tsx");
const outPath = path.join(root, "web/src/routes/teams/teamRouteShellModel.ts");
const lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

const find = (pred, from = 0) => {
  for (let i = from; i < lines.length; i += 1) {
    if (pred(lines[i])) return i;
  }
  return -1;
};

const chatLabelsStart = find((l) => l.startsWith("const SOURCE_COLLECTION_STAGE_CHAT_LABELS"));
const parseStart = find((l) => l.startsWith("function parseSourceCollectionStageModuleId("));
const nodeDragStart = find((l) => l.startsWith("type NodeDragState ="));
const feedbackStart = find((l) => l.startsWith("function researchStageStartFeedbackText("));
const roleBadgeStart = find((l) => l.startsWith("function roleBadgeTone("));
const teamNodeStart = find((l) => l.startsWith("function teamNodeFunctionLabel("));
const nodeToneStart = find((l) => l.startsWith("function nodeTone("));
const latestRoundStart = find((l) => l.startsWith("function latestChatRoomRound("));
const qualityBoundStart = find((l) => l.startsWith("function workflowQualityToneBound("));
const graphPayloadStart = find((l) => l.startsWith("function isWorkflowCandidateGraphPayload("));
const routeExportStart = find((l) => l.startsWith("export function TeamsRoute("));

const markers = {
  chatLabelsStart,
  parseStart,
  nodeDragStart,
  feedbackStart,
  roleBadgeStart,
  teamNodeStart,
  nodeToneStart,
  latestRoundStart,
  qualityBoundStart,
  graphPayloadStart,
  routeExportStart,
};
if (Object.values(markers).some((i) => i < 0)) {
  console.error("marker missing", markers);
  process.exit(1);
}

function exportBlock(block) {
  return block
    .map((line) => {
      if (line.startsWith("function ")) return `export ${line}`;
      if (line.startsWith("const SOURCE_COLLECTION_STAGE_CHAT_LABELS")) {
        return line.replace(/^const /, "export const ");
      }
      return line;
    })
    .join("\n");
}

const chatLabelsBlock = exportBlock(lines.slice(chatLabelsStart, parseStart));
const parseBlock = exportBlock(lines.slice(parseStart, nodeDragStart));
const feedbackBlock = exportBlock(lines.slice(feedbackStart, roleBadgeStart));
const labelsBlock = exportBlock(lines.slice(teamNodeStart, nodeToneStart));
const latestRoundBlock = exportBlock(lines.slice(latestRoundStart, qualityBoundStart));
const graphBlock = exportBlock(lines.slice(graphPayloadStart, routeExportStart));

const content = `/**
 * TeamsRoute pure shell helpers (structure M5).
 * Pure: no React hooks / Query / DOM. Style-bound helpers stay in TeamsRoute.
 */
import type { ChatRoomDetail, TeamCanvasNode, TeamWorkflowCandidate, TeamWorkflowCandidateGraphPayload } from "../../api/types";
import type { ResearchStageRoundStartPayload } from "./workflowStartMutationModel";
import { sourceCollectionRunLabel } from "./source-collection/runModel";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";
import { isRecord } from "./workflowPresentation";

${chatLabelsBlock}

${parseBlock}

${feedbackBlock}

${labelsBlock}

${latestRoundBlock}

${graphBlock}
`;

fs.writeFileSync(outPath, content.replace(/export export /g, "export ").replace(/\n{3,}/g, "\n\n") + "\n");

// Remove from route (high line first)
const removeRanges = [
  [graphPayloadStart, routeExportStart],
  [latestRoundStart, qualityBoundStart],
  [teamNodeStart, nodeToneStart],
  [feedbackStart, roleBadgeStart],
  [chatLabelsStart, nodeDragStart], // chat labels + parse + through NodeDragState start - wait, keep NodeDragState
].sort((a, b) => b[0] - a[0]);

// Fix first range: chatLabels through parse end is chatLabelsStart..nodeDragStart (keeps NodeDragState)
// parse is inside chatLabelsStart..nodeDragStart

let next = lines;
for (const [start, end] of removeRanges) {
  next = [...next.slice(0, start), ...next.slice(end)];
}

let route = next.join("\n");

const imp = `import {
  candidatePaperNoteChunkPlanSummary,
  canvasNodeStatusLabel,
  isWorkflowCandidateGraphPayload,
  latestChatRoomRound,
  latestWorkflowCandidate,
  parseSourceCollectionStageModuleId,
  researchStageStartFeedbackText,
  SOURCE_COLLECTION_STAGE_CHAT_LABELS,
  sourceCandidateHasCompletedExtraction,
  teamNodeFunctionLabel,
  workflowCandidateGraphFromCandidate,
} from "./teams/teamRouteShellModel";
`;

if (!route.includes("teamRouteShellModel")) {
  route = route.replace(
    'from "./teams/workflowPresentation";',
    `from "./teams/workflowPresentation";\n${imp}`,
  );
  // may need different anchor
  if (!route.includes("teamRouteShellModel")) {
    route = route.replace(
      'from "./teams/workflowTone";',
      `from "./teams/workflowTone";\n${imp}`,
    );
  }
  if (!route.includes("teamRouteShellModel")) {
    // append after useTeamShellMutations import area
    route = route.replace(
      'from "./teams/useTeamShellMutations";',
      `from "./teams/useTeamShellMutations";\n${imp}`,
    );
  }
}

fs.writeFileSync(routePath, route.replace(/\n{3,}/g, "\n\n") + "\n");
console.log("wrote", outPath);
console.log("TeamsRoute lines", route.split(/\n/).length);
console.log("local parse left", /function parseSourceCollectionStageModuleId\(/.test(route));
console.log("local teamNode left", /function teamNodeFunctionLabel\(/.test(route));
console.log("has import", route.includes("teamRouteShellModel"));
console.log("roleBadge still local", /function roleBadgeTone\(/.test(route));
