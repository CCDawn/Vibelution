/**
 * SC inject: stage agent cards for the controls rail.
 */
import { TeamSourceCollectionStageAgentsPanel } from "./teamLazyPanels";
import {
  buildSourceCollectionStageAgentCards,
  type SourceCollectionStageAgentBindingLike,
} from "./source-collection/stageAgentsPresentation";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";

export type TeamSourceCollectionStageAgentsInjectProps = {
  lang: "zh" | "en";
  stageId: SourceCollectionStageModuleId | string;
  bindings: SourceCollectionStageAgentBindingLike[];
  agentSummaryPending: boolean;
  agentSummaryFetching: boolean;
  agentSummaryError: boolean;
  teamId?: string;
  returnTo: string;
};

export function TeamSourceCollectionStageAgentsInject({
  lang,
  stageId,
  bindings,
  agentSummaryPending,
  agentSummaryFetching,
  agentSummaryError,
  teamId,
  returnTo,
}: TeamSourceCollectionStageAgentsInjectProps) {
  if (!bindings.length) {
    return null;
  }
  const agents = buildSourceCollectionStageAgentCards({
    stageId,
    bindings,
    lang,
    agentSummaryPending,
    agentSummaryFetching,
    agentSummaryError,
    teamId,
    returnTo,
  });
  return <TeamSourceCollectionStageAgentsPanel lang={lang} agents={agents} />;
}
