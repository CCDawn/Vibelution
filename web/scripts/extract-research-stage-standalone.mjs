/**
 * Wave 8I: extract renderResearchStageStandalonePage into TeamResearchStageStandalonePagePanel.
 * Usage (from web/): node scripts/extract-research-stage-standalone.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/TeamsRoute.tsx";
const outPath = "src/routes/TeamResearchStageStandalonePagePanel.tsx";
const src = readFileSync(routePath, "utf8");

const start = src.indexOf("  function renderResearchStageStandalonePage(stageView: Exclude<ResearchStageWorkspaceView, \"knowledge_collection\">) {");
const end = src.indexOf("  function addNode() {");
if (start < 0 || end <= start) {
  console.error("markers not found", start, end);
  process.exit(1);
}

const fn = src.slice(start, end);
const bodyStart = fn.indexOf("{");
const body = fn.slice(bodyStart);
const statements = body.slice(1, body.lastIndexOf("}"));

const header = `/**
 * Research stage standalone page (experiment / iteration workspaces).
 * Wave 8I: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { ArrowLeft, Play, Plus, RefreshCw, Users } from "lucide-react";
import { Link } from "react-router-dom";

import type { Team } from "../api/types";
import { VButton, VNativeButton } from "../components/vui";
import {
  researchDiagnosticStatusLabel,
  researchIterationLifecycleStatusLabel,
  type ExperimentPlanRecord,
  type ExperimentPlanningStatusPayload,
} from "./teams/experimentLoopModel";
import { RESEARCH_TEAM_ID } from "./TeamsRoute.canvasData";
import {
  researchWorkspaceStageRoute,
  researchWorkspaceViewLabel,
  teamWorkspaceRoute,
  type ResearchStageWorkspaceView,
} from "./teams/researchWorkspaceModel";
import type {
  ResearchStagePhaseStatus,
  ResearchStageType,
} from "./teams/source-collection/stageProjection";
import { teamChatRoomRoute } from "./teams/researchStageAgentPresentation";
import { ResearchMemoryEvidencePanel } from "./teams/ResearchMemoryEvidencePanel";
import researchStyles from "./TeamsRoute.research.styles";
import shellStyles from "./TeamsRoute.styles";

const styles = { ...shellStyles, ...researchStyles } as Record<string, string>;

type Lang = "zh" | "en";
type StageView = Exclude<ResearchStageWorkspaceView, "knowledge_collection">;

export type TeamResearchStageStandalonePagePanelProps = {
  stageView: StageView;
  lang: Lang;
  researchStagePhases: ResearchStagePhaseStatus[];
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  selectedTeam: Team | null | undefined;
  selectedTeamStartResearchStagePending: boolean;
  linkedChatRoomId: string;
  syncTeamChatRoomMutation: { mutate: (teamId: string) => void };
  activeTeamMemberCount: number;
  selectedTeamSyncPending: boolean;
  researchStageRoundStatusQuery: { isFetching: boolean; refetch: () => unknown };
  renderResearchStageAgentPanel: (stageType: ResearchStageType, variant?: "compact" | "page") => ReactNode;
  launchResearchStage: (stageType: ResearchStageType, mode?: "continue_or_start" | "new_round") => void;
  selectedTeamStartResearchStageError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamStartResearchStageResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  researchStageStartFeedbackText: (payload: any, lang: Lang, stageLabel?: string) => string;
  renderExperimentPlanningLedgerPanel: () => ReactNode;
  renderResearchLoopPanel: (activePlan: ExperimentPlanRecord | null, variant?: "experiment" | "iteration") => ReactNode;
};

export function TeamResearchStageStandalonePagePanel(props: TeamResearchStageStandalonePagePanelProps) {
  const {
    stageView,
    lang,
    researchStagePhases,
    experimentPlanningStatus,
    selectedTeam,
    selectedTeamStartResearchStagePending,
    linkedChatRoomId,
    syncTeamChatRoomMutation,
    activeTeamMemberCount,
    selectedTeamSyncPending,
    researchStageRoundStatusQuery,
    renderResearchStageAgentPanel,
    launchResearchStage,
    selectedTeamStartResearchStageError,
    selectedTeamStartResearchStageResult,
    researchStageStartFeedbackText,
    renderExperimentPlanningLedgerPanel,
    renderResearchLoopPanel,
  } = props;

`;

const fixed = `${header}${statements}
}
`;

writeFileSync(outPath, fixed);
console.log("wrote", outPath, "chars", fixed.length);

const replacement = `  function renderResearchStageStandalonePage(stageView: Exclude<ResearchStageWorkspaceView, "knowledge_collection">) {
    return (
      <TeamResearchStageStandalonePagePanel
        stageView={stageView}
        lang={lang}
        researchStagePhases={researchStagePhases}
        experimentPlanningStatus={experimentPlanningStatus}
        selectedTeam={selectedTeam}
        selectedTeamStartResearchStagePending={selectedTeamStartResearchStagePending}
        linkedChatRoomId={linkedChatRoomId || ""}
        syncTeamChatRoomMutation={syncTeamChatRoomMutation}
        activeTeamMemberCount={activeTeamMemberCount}
        selectedTeamSyncPending={selectedTeamSyncPending}
        researchStageRoundStatusQuery={researchStageRoundStatusQuery}
        renderResearchStageAgentPanel={renderResearchStageAgentPanel}
        launchResearchStage={launchResearchStage}
        selectedTeamStartResearchStageError={selectedTeamStartResearchStageError}
        selectedTeamStartResearchStageResult={selectedTeamStartResearchStageResult}
        researchStageStartFeedbackText={researchStageStartFeedbackText}
        renderExperimentPlanningLedgerPanel={renderExperimentPlanningLedgerPanel}
        renderResearchLoopPanel={renderResearchLoopPanel}
      />
    );
  }

`;

let wired = src.slice(0, start) + replacement + src.slice(end);
if (!wired.includes('createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageStandalonePagePanel")')) {
  wired = wired.replace(
    'const TeamResearchStageLauncherPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageLauncherPanel");',
    `const TeamResearchStageLauncherPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageLauncherPanel");
const TeamResearchStageStandalonePagePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageStandalonePagePanel");`,
  );
}
writeFileSync(routePath, wired);
console.log("patched TeamsRoute.tsx");
