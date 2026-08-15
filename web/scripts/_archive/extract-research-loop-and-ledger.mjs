/**
 * Wave 8J: extract renderResearchLoopPanel + renderExperimentPlanningLedgerPanel
 * into secondary-lazy panels with prop injection.
 * Usage (from web/): node scripts/extract-research-loop-and-ledger.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/TeamsRoute.tsx";
const loopOut = "src/routes/TeamResearchLoopPanel.tsx";
const ledgerOut = "src/routes/TeamExperimentPlanningLedgerPanel.tsx";
const src = readFileSync(routePath, "utf8");

const loopStart = src.indexOf("  function renderResearchLoopPanel(activePlan: ExperimentPlanRecord | null, variant: \"experiment\" | \"iteration\" = \"experiment\") {");
const ledgerStart = src.indexOf("  function renderExperimentPlanningLedgerPanel() {");
const standaloneStart = src.indexOf("  function renderResearchStageStandalonePage(stageView: Exclude<ResearchStageWorkspaceView, \"knowledge_collection\">) {");
if (loopStart < 0 || ledgerStart <= loopStart || standaloneStart <= ledgerStart) {
  console.error("markers", { loopStart, ledgerStart, standaloneStart });
  process.exit(1);
}

function extractBody(fnText) {
  const bodyStart = fnText.indexOf("{");
  const body = fnText.slice(bodyStart);
  return body.slice(1, body.lastIndexOf("}"));
}

const loopFn = src.slice(loopStart, ledgerStart);
const ledgerFn = src.slice(ledgerStart, standaloneStart);
const loopStatements = extractBody(loopFn);
const ledgerStatements = extractBody(ledgerFn);

const loopHeader = `/**
 * Research loop template / evidence / decision panel.
 * Wave 8J: extracted from TeamsRoute.tsx for domain componentization.
 */
import { AlertTriangle, Plus, RefreshCw, Save, Send } from "lucide-react";

import type { Team } from "../api/types";
import { VNativeButton, VNativeInput, VNativeSelect } from "../components/vui";
import {
  RESEARCH_LOOP_DECISION_VALUES,
  RESEARCH_LOOP_EVIDENCE_STATUSES,
  type ExperimentPlanRecord,
  type ResearchLoopCreateDraft,
  type ResearchLoopDecisionDraft,
  type ResearchLoopDecisionValue,
  type ResearchLoopEvidenceDraft,
  type ResearchLoopEvidenceStatus,
  type ResearchLoopRecord,
  type ResearchLoopStatusPayload,
  type ResearchLoopTemplatesPayload,
} from "./teams/experimentLoopModel";
import researchStyles from "./TeamsRoute.research.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...researchStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamResearchLoopPanelProps = {
  activePlan: ExperimentPlanRecord | null;
  variant?: "experiment" | "iteration";
  lang: Lang;
  selectedTeam: Team | null | undefined;
  researchLoopStatus: ResearchLoopStatusPayload | null | undefined;
  researchLoopTemplatesPayload: ResearchLoopTemplatesPayload | null | undefined;
  selectedResearchLoopTemplateId: string;
  setSelectedResearchLoopTemplateId: (id: string) => void;
  researchLoopCreateDraft: ResearchLoopCreateDraft;
  setResearchLoopCreateDraft: (updater: (draft: ResearchLoopCreateDraft) => ResearchLoopCreateDraft) => void;
  researchLoopEvidenceDraft: ResearchLoopEvidenceDraft;
  setResearchLoopEvidenceDraft: (updater: (draft: ResearchLoopEvidenceDraft) => ResearchLoopEvidenceDraft) => void;
  researchLoopDecisionDraft: ResearchLoopDecisionDraft;
  setResearchLoopDecisionDraft: (updater: (draft: ResearchLoopDecisionDraft) => ResearchLoopDecisionDraft) => void;
  sourceCollectionDraft: { goal: string };
  researchLoopStatusQuery: { isFetching: boolean; refetch: () => unknown };
  selectedTeamCreateResearchLoopPending: boolean;
  selectedTeamCreateResearchLoopError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamCreateResearchLoopResult: any;
  selectedTeamRecordResearchLoopEvidencePending: boolean;
  selectedTeamRecordResearchLoopEvidenceError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRecordResearchLoopEvidenceResult: any;
  selectedTeamRecordResearchLoopDecisionPending: boolean;
  selectedTeamRecordResearchLoopDecisionError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRecordResearchLoopDecisionResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  materializeResearchLoopIterationDesignMutation: any;
  createResearchLoopFromWorkspace: (plan: ExperimentPlanRecord | null) => void;
  recordResearchLoopEvidenceFromWorkspace: (loop: ResearchLoopRecord) => void;
  recordResearchLoopDecisionFromWorkspace: (loop: ResearchLoopRecord) => void;
};

export function TeamResearchLoopPanel(props: TeamResearchLoopPanelProps) {
  const {
    activePlan,
    variant = "experiment",
    lang,
    selectedTeam,
    researchLoopStatus,
    researchLoopTemplatesPayload,
    selectedResearchLoopTemplateId,
    setSelectedResearchLoopTemplateId,
    researchLoopCreateDraft,
    setResearchLoopCreateDraft,
    researchLoopEvidenceDraft,
    setResearchLoopEvidenceDraft,
    researchLoopDecisionDraft,
    setResearchLoopDecisionDraft,
    sourceCollectionDraft,
    researchLoopStatusQuery,
    selectedTeamCreateResearchLoopPending,
    selectedTeamCreateResearchLoopError,
    selectedTeamCreateResearchLoopResult,
    selectedTeamRecordResearchLoopEvidencePending,
    selectedTeamRecordResearchLoopEvidenceError,
    selectedTeamRecordResearchLoopEvidenceResult,
    selectedTeamRecordResearchLoopDecisionPending,
    selectedTeamRecordResearchLoopDecisionError,
    selectedTeamRecordResearchLoopDecisionResult,
    materializeResearchLoopIterationDesignMutation,
    createResearchLoopFromWorkspace,
    recordResearchLoopEvidenceFromWorkspace,
    recordResearchLoopDecisionFromWorkspace,
  } = props;

`;

const ledgerHeader = `/**
 * Experiment planning ledger (method panel, baseline/smoke/full-run, knowledge ingestion).
 * Wave 8J: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Save } from "lucide-react";

import type { ExperimentMethodId, Team } from "../api/types";
import { VNativeButton, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
import {
  EXPERIMENT_FULL_RUN_RESULT_STATUSES,
  EXPERIMENT_SMOKE_RESULT_STATUSES,
  type ExperimentBaselineArtifactDraft,
  type ExperimentFullRunResultDraft,
  type ExperimentFullRunResultStatus,
  type ExperimentKnowledgeIngestionDraft,
  type ExperimentPlanRecord,
  type ExperimentPlanningStatusPayload,
  type ExperimentSmokeResultDraft,
  type ExperimentSmokeResultStatus,
} from "./teams/experimentLoopModel";
import { TeamExperimentMethodPanel, type ExperimentPlanMethodRequest } from "./TeamExperimentMethodPanel";
import experimentStyles from "./TeamsRoute.experiment.styles";
import researchStyles from "./TeamsRoute.research.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...experimentStyles, ...researchStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamExperimentPlanningLedgerPanelProps = {
  lang: Lang;
  selectedTeam: Team | null | undefined;
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  experimentPlanningStatusQuery: { isFetching: boolean; refetch: () => unknown };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  experimentMethodCatalogQuery: { data?: any; isFetching: boolean; error?: unknown };
  preferredExperimentMethod: string;
  searchParams: URLSearchParams;
  experimentBaselineArtifactDraft: ExperimentBaselineArtifactDraft;
  setExperimentBaselineArtifactDraft: (updater: (draft: ExperimentBaselineArtifactDraft) => ExperimentBaselineArtifactDraft) => void;
  experimentSmokeResultDraft: ExperimentSmokeResultDraft;
  setExperimentSmokeResultDraft: (updater: (draft: ExperimentSmokeResultDraft) => ExperimentSmokeResultDraft) => void;
  experimentFullRunResultDraft: ExperimentFullRunResultDraft;
  setExperimentFullRunResultDraft: (updater: (draft: ExperimentFullRunResultDraft) => ExperimentFullRunResultDraft) => void;
  experimentKnowledgeIngestionDraft: ExperimentKnowledgeIngestionDraft;
  setExperimentKnowledgeIngestionDraft: (updater: (draft: ExperimentKnowledgeIngestionDraft) => ExperimentKnowledgeIngestionDraft) => void;
  selectedTeamCreateExperimentPlanPending: boolean;
  selectedTeamCreateExperimentPlanError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamCreateExperimentPlanResult: any;
  selectedTeamFreezeExperimentDesignPending: boolean;
  selectedTeamFreezeExperimentDesignError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamFreezeExperimentDesignResult: any;
  selectedTeamRegisterExperimentBaselineArtifactPending: boolean;
  selectedTeamRegisterExperimentBaselineArtifactError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRegisterExperimentBaselineArtifactResult: any;
  selectedTeamRegisterExperimentSmokeResultPending: boolean;
  selectedTeamRegisterExperimentSmokeResultError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRegisterExperimentSmokeResultResult: any;
  selectedTeamRegisterExperimentFullRunResultPending: boolean;
  selectedTeamRegisterExperimentFullRunResultError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRegisterExperimentFullRunResultResult: any;
  selectedTeamRequestExperimentKnowledgeIngestionPending: boolean;
  selectedTeamRequestExperimentKnowledgeIngestionError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRequestExperimentKnowledgeIngestionResult: any;
  createExperimentPlanFromWorkspace: (methodRequest?: ExperimentPlanMethodRequest) => void;
  freezeExperimentDesignFromWorkspace: (plan: ExperimentPlanRecord) => void;
  registerExperimentBaselineArtifactFromWorkspace: (plan: ExperimentPlanRecord) => void;
  registerExperimentSmokeResultFromWorkspace: (plan: ExperimentPlanRecord) => void;
  registerExperimentFullRunResultFromWorkspace: (plan: ExperimentPlanRecord) => void;
  requestExperimentKnowledgeIngestionFromWorkspace: (plan: ExperimentPlanRecord) => void;
  renderResearchLoopPanel: (activePlan: ExperimentPlanRecord | null, variant?: "experiment" | "iteration") => ReactNode;
};

export function TeamExperimentPlanningLedgerPanel(props: TeamExperimentPlanningLedgerPanelProps) {
  const {
    lang,
    selectedTeam,
    experimentPlanningStatus,
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    preferredExperimentMethod,
    searchParams,
    experimentBaselineArtifactDraft,
    setExperimentBaselineArtifactDraft,
    experimentSmokeResultDraft,
    setExperimentSmokeResultDraft,
    experimentFullRunResultDraft,
    setExperimentFullRunResultDraft,
    experimentKnowledgeIngestionDraft,
    setExperimentKnowledgeIngestionDraft,
    selectedTeamCreateExperimentPlanPending,
    selectedTeamCreateExperimentPlanError,
    selectedTeamCreateExperimentPlanResult,
    selectedTeamFreezeExperimentDesignPending,
    selectedTeamFreezeExperimentDesignError,
    selectedTeamFreezeExperimentDesignResult,
    selectedTeamRegisterExperimentBaselineArtifactPending,
    selectedTeamRegisterExperimentBaselineArtifactError,
    selectedTeamRegisterExperimentBaselineArtifactResult,
    selectedTeamRegisterExperimentSmokeResultPending,
    selectedTeamRegisterExperimentSmokeResultError,
    selectedTeamRegisterExperimentSmokeResultResult,
    selectedTeamRegisterExperimentFullRunResultPending,
    selectedTeamRegisterExperimentFullRunResultError,
    selectedTeamRegisterExperimentFullRunResultResult,
    selectedTeamRequestExperimentKnowledgeIngestionPending,
    selectedTeamRequestExperimentKnowledgeIngestionError,
    selectedTeamRequestExperimentKnowledgeIngestionResult,
    createExperimentPlanFromWorkspace,
    freezeExperimentDesignFromWorkspace,
    registerExperimentBaselineArtifactFromWorkspace,
    registerExperimentSmokeResultFromWorkspace,
    registerExperimentFullRunResultFromWorkspace,
    requestExperimentKnowledgeIngestionFromWorkspace,
    renderResearchLoopPanel,
  } = props;

`;

// Drop unused result vars if body only uses some - keep destructuring for future safety.
// TypeScript may warn on unused - we'll eslint ignore or prefix later if needed.

writeFileSync(loopOut, `${loopHeader}${loopStatements}\n}\n`);
writeFileSync(ledgerOut, `${ledgerHeader}${ledgerStatements}\n}\n`);
console.log("wrote", loopOut, "chars", loopHeader.length + loopStatements.length);
console.log("wrote", ledgerOut, "chars", ledgerHeader.length + ledgerStatements.length);
console.log("loop 实验迭代", (loopHeader + loopStatements).includes("实验迭代决策"));
console.log("ledger 实验计划账本", (ledgerHeader + ledgerStatements).includes("实验计划账本"));

const loopWrapper = `  function renderResearchLoopPanel(activePlan: ExperimentPlanRecord | null, variant: "experiment" | "iteration" = "experiment") {
    return (
      <TeamResearchLoopPanel
        activePlan={activePlan}
        variant={variant}
        lang={lang}
        selectedTeam={selectedTeam}
        researchLoopStatus={researchLoopStatus}
        researchLoopTemplatesPayload={researchLoopTemplatesPayload}
        selectedResearchLoopTemplateId={selectedResearchLoopTemplateId}
        setSelectedResearchLoopTemplateId={setSelectedResearchLoopTemplateId}
        researchLoopCreateDraft={researchLoopCreateDraft}
        setResearchLoopCreateDraft={setResearchLoopCreateDraft}
        researchLoopEvidenceDraft={researchLoopEvidenceDraft}
        setResearchLoopEvidenceDraft={setResearchLoopEvidenceDraft}
        researchLoopDecisionDraft={researchLoopDecisionDraft}
        setResearchLoopDecisionDraft={setResearchLoopDecisionDraft}
        sourceCollectionDraft={sourceCollectionDraft}
        researchLoopStatusQuery={researchLoopStatusQuery}
        selectedTeamCreateResearchLoopPending={selectedTeamCreateResearchLoopPending}
        selectedTeamCreateResearchLoopError={selectedTeamCreateResearchLoopError}
        selectedTeamCreateResearchLoopResult={selectedTeamCreateResearchLoopResult}
        selectedTeamRecordResearchLoopEvidencePending={selectedTeamRecordResearchLoopEvidencePending}
        selectedTeamRecordResearchLoopEvidenceError={selectedTeamRecordResearchLoopEvidenceError}
        selectedTeamRecordResearchLoopEvidenceResult={selectedTeamRecordResearchLoopEvidenceResult}
        selectedTeamRecordResearchLoopDecisionPending={selectedTeamRecordResearchLoopDecisionPending}
        selectedTeamRecordResearchLoopDecisionError={selectedTeamRecordResearchLoopDecisionError}
        selectedTeamRecordResearchLoopDecisionResult={selectedTeamRecordResearchLoopDecisionResult}
        materializeResearchLoopIterationDesignMutation={materializeResearchLoopIterationDesignMutation}
        createResearchLoopFromWorkspace={createResearchLoopFromWorkspace}
        recordResearchLoopEvidenceFromWorkspace={recordResearchLoopEvidenceFromWorkspace}
        recordResearchLoopDecisionFromWorkspace={recordResearchLoopDecisionFromWorkspace}
      />
    );
  }

`;

const ledgerWrapper = `  function renderExperimentPlanningLedgerPanel() {
    return (
      <TeamExperimentPlanningLedgerPanel
        lang={lang}
        selectedTeam={selectedTeam}
        experimentPlanningStatus={experimentPlanningStatus}
        experimentPlanningStatusQuery={experimentPlanningStatusQuery}
        experimentMethodCatalogQuery={experimentMethodCatalogQuery}
        preferredExperimentMethod={preferredExperimentMethod}
        searchParams={searchParams}
        experimentBaselineArtifactDraft={experimentBaselineArtifactDraft}
        setExperimentBaselineArtifactDraft={setExperimentBaselineArtifactDraft}
        experimentSmokeResultDraft={experimentSmokeResultDraft}
        setExperimentSmokeResultDraft={setExperimentSmokeResultDraft}
        experimentFullRunResultDraft={experimentFullRunResultDraft}
        setExperimentFullRunResultDraft={setExperimentFullRunResultDraft}
        experimentKnowledgeIngestionDraft={experimentKnowledgeIngestionDraft}
        setExperimentKnowledgeIngestionDraft={setExperimentKnowledgeIngestionDraft}
        selectedTeamCreateExperimentPlanPending={selectedTeamCreateExperimentPlanPending}
        selectedTeamCreateExperimentPlanError={selectedTeamCreateExperimentPlanError}
        selectedTeamCreateExperimentPlanResult={selectedTeamCreateExperimentPlanResult}
        selectedTeamFreezeExperimentDesignPending={selectedTeamFreezeExperimentDesignPending}
        selectedTeamFreezeExperimentDesignError={selectedTeamFreezeExperimentDesignError}
        selectedTeamFreezeExperimentDesignResult={selectedTeamFreezeExperimentDesignResult}
        selectedTeamRegisterExperimentBaselineArtifactPending={selectedTeamRegisterExperimentBaselineArtifactPending}
        selectedTeamRegisterExperimentBaselineArtifactError={selectedTeamRegisterExperimentBaselineArtifactError}
        selectedTeamRegisterExperimentBaselineArtifactResult={selectedTeamRegisterExperimentBaselineArtifactResult}
        selectedTeamRegisterExperimentSmokeResultPending={selectedTeamRegisterExperimentSmokeResultPending}
        selectedTeamRegisterExperimentSmokeResultError={selectedTeamRegisterExperimentSmokeResultError}
        selectedTeamRegisterExperimentSmokeResultResult={selectedTeamRegisterExperimentSmokeResultResult}
        selectedTeamRegisterExperimentFullRunResultPending={selectedTeamRegisterExperimentFullRunResultPending}
        selectedTeamRegisterExperimentFullRunResultError={selectedTeamRegisterExperimentFullRunResultError}
        selectedTeamRegisterExperimentFullRunResultResult={selectedTeamRegisterExperimentFullRunResultResult}
        selectedTeamRequestExperimentKnowledgeIngestionPending={selectedTeamRequestExperimentKnowledgeIngestionPending}
        selectedTeamRequestExperimentKnowledgeIngestionError={selectedTeamRequestExperimentKnowledgeIngestionError}
        selectedTeamRequestExperimentKnowledgeIngestionResult={selectedTeamRequestExperimentKnowledgeIngestionResult}
        createExperimentPlanFromWorkspace={createExperimentPlanFromWorkspace}
        freezeExperimentDesignFromWorkspace={freezeExperimentDesignFromWorkspace}
        registerExperimentBaselineArtifactFromWorkspace={registerExperimentBaselineArtifactFromWorkspace}
        registerExperimentSmokeResultFromWorkspace={registerExperimentSmokeResultFromWorkspace}
        registerExperimentFullRunResultFromWorkspace={registerExperimentFullRunResultFromWorkspace}
        requestExperimentKnowledgeIngestionFromWorkspace={requestExperimentKnowledgeIngestionFromWorkspace}
        renderResearchLoopPanel={renderResearchLoopPanel}
      />
    );
  }

`;

const next = src.slice(0, loopStart) + loopWrapper + ledgerWrapper + src.slice(standaloneStart);
writeFileSync(routePath, next);
console.log("rewrote TeamsRoute.tsx", "new len", next.length, "delta", next.length - src.length);

// Ensure lazy declarations exist
let route = readFileSync(routePath, "utf8");
if (!route.includes('createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchLoopPanel")')) {
  route = route.replace(
    'const TeamResearchStageStandalonePagePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageStandalonePagePanel");',
    `const TeamResearchStageStandalonePagePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageStandalonePagePanel");
const TeamResearchLoopPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchLoopPanel");
const TeamExperimentPlanningLedgerPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamExperimentPlanningLedgerPanel");`,
  );
  writeFileSync(routePath, route);
  console.log("added lazy panel declarations");
}

// Secondary barrel
const secondaryPath = "src/routes/teams/teamSecondaryPanels.ts";
let secondary = readFileSync(secondaryPath, "utf8");
if (!secondary.includes("TeamResearchLoopPanel")) {
  secondary = secondary.replace(
    'export { TeamResearchStageStandalonePagePanel } from "../TeamResearchStageStandalonePagePanel";',
    `export { TeamResearchStageStandalonePagePanel } from "../TeamResearchStageStandalonePagePanel";
export { TeamResearchLoopPanel } from "../TeamResearchLoopPanel";
export { TeamExperimentPlanningLedgerPanel } from "../TeamExperimentPlanningLedgerPanel";`,
  );
  writeFileSync(secondaryPath, secondary);
  console.log("updated teamSecondaryPanels.ts");
}
