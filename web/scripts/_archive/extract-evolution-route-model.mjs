/**
 * M4 structure: extract EvolutionRoute pure presentation/helpers into evolution/evolutionRouteModel.ts
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/EvolutionRoute.tsx");
const outPath = path.join(root, "web/src/routes/evolution/evolutionRouteModel.ts");
const lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

const find = (pred, from = 0) => {
  for (let i = from; i < lines.length; i += 1) {
    if (pred(lines[i])) return i;
  }
  return -1;
};

const memberRoleStart = find((l) => l.startsWith("type SupervisedMemberRole ="));
const preflightTypeStart = find((l) => l.startsWith("type SupervisedPreflightIssue ="));
const libraryFiltersStart = find((l) => l.startsWith("const LIBRARY_STATUS_FILTERS"));
const memberRolesConst = find((l) => l.startsWith("const SUPERVISED_RUN_MEMBER_ROLES"));
const mentalModeStart = find((l) => l.startsWith("type SupervisedMentalModelMode"));
const clampStart = find((l) => l.startsWith("function clampScore("));
const routeExportStart = find((l) => l.startsWith("export function EvolutionRoute("));

const markers = {
  memberRoleStart,
  preflightTypeStart,
  libraryFiltersStart,
  memberRolesConst,
  mentalModeStart,
  clampStart,
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
      if (line.startsWith("type ")) return `export ${line}`;
      if (line.startsWith("const SUPERVISED_RUN_MEMBER_ROLES")) return line.replace(/^const /, "export const ");
      if (line.startsWith("const SUPERVISED_WORKFLOW_STEPS")) return line.replace(/^const /, "export const ");
      if (line.startsWith("const LOCAL_SUPERVISED_RUN_PREFIX")) return line.replace(/^const /, "export const ");
      if (line.startsWith("type ProposalEditDraft")) return `export ${line}`;
      if (line.startsWith("type SupervisedMentalModelMode")) return `export ${line}`;
      return line;
    })
    .join("\n");
}

// Types: SupervisedMemberRole through SupervisedPreflightIssue
const typesBlock = exportBlock(lines.slice(memberRoleStart, libraryFiltersStart));
// Constants: SUPERVISED_RUN_MEMBER_ROLES through LOCAL_SUPERVISED_RUN_PREFIX + ProposalEditDraft + MentalMode
const constBlock = exportBlock(lines.slice(memberRolesConst, clampStart));
// Pure functions: clampScore through compactCaseObject (before EvolutionRoute)
const pureBlock = exportBlock(lines.slice(clampStart, routeExportStart));

const content = `/**
 * Evolution route pure presentation helpers (structure M4).
 * Pure: no React hooks / Query / DOM.
 */
import type {
  EvolutionActiveRun,
  EvolutionActiveRunAgentBinding,
  EvolutionLibraryEntry,
  EvolutionProposalDetail,
  EvolutionRun,
  EvolutionWorkbench,
  EvolutionWorkflowStep,
} from "../../api/types";
import { modelDisplayLabel } from "../agentDisplay";
import { supervisedDecisionLabel } from "../supervisedRunRecordLabel";

${typesBlock}

${constBlock}

${pureBlock}
`;

fs.writeFileSync(outPath, content.replace(/export export /g, "export ").replace(/\n{3,}/g, "\n\n") + "\n");

// Rebuild route: remove extracted ranges (high first)
const removeRanges = [
  [clampStart, routeExportStart],
  [memberRolesConst, clampStart],
  [memberRoleStart, libraryFiltersStart],
].sort((a, b) => b[0] - a[0]);

let next = lines;
for (const [start, end] of removeRanges) {
  next = [...next.slice(0, start), ...next.slice(end)];
}

let route = next.join("\n");

const imp = `import {
  activeSupervisedWorkflowStep,
  buildSupervisedStartPlaceholder,
  canOpenProposalSourceRun,
  clampScore,
  compactCaseObject,
  compactTimestamp,
  datasetBenchmarkDetail,
  datasetCatalogStatusLabel,
  datasetUsabilityLabel,
  displaySupervisedRunStatus,
  displaySupervisedRunSummary,
  displaySupervisedTechnicalText,
  formatTurnRange,
  hasSupervisedAgentBindings,
  isLocalSupervisedStartPlaceholder,
  isSelfEvolutionCandidateItem,
  LOCAL_SUPERVISED_RUN_PREFIX,
  proposalDisplaySourceRun,
  proposalEditDraftFromDetail,
  SUPERVISED_RUN_MEMBER_ROLES,
  SUPERVISED_WORKFLOW_STEPS,
  supervisedMemberAgentManagementRoute,
  supervisedMemberChatRoute,
  supervisedMemberModelId,
  supervisedMemberModelLabel,
  supervisedPreflightIssue,
  supervisedProposalStatusLabel,
  supervisedRunBucketLabel,
  supervisedWorkflowStepLabel,
  toLimitInput,
  type ProposalEditDraft,
  type SupervisedClosedLoopRecord,
  type SupervisedMemberRole,
  type SupervisedMentalModelMode,
  type SupervisedPreflightIssue,
  type SupervisedRunMember,
  type SupervisedWorkflowCard,
  type SupervisedWorkflowDefinition,
  type SupervisedWorkflowStepId,
} from "./evolution/evolutionRouteModel";
`;

if (!route.includes("evolutionRouteModel")) {
  route = route.replace(
    'from "./evolution/useEvolutionRunMutations";',
    `from "./evolution/useEvolutionRunMutations";\n${imp}`,
  );
}

fs.writeFileSync(routePath, route.replace(/\n{3,}/g, "\n\n") + "\n");
console.log("wrote", outPath);
console.log("EvolutionRoute lines", route.split(/\n/).length);
console.log("local clampScore left", /function clampScore\(/.test(route));
console.log("has model import", route.includes("evolutionRouteModel"));
