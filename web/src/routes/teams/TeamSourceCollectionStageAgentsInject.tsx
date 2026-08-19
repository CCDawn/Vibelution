/**
 * SC inject: stage agent cards for the controls rail.
 */
import { useMemo } from "react";

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
  // Memoized so the memoized panel below keeps a stable agents identity across
  // unrelated SC polls (bindings come from React Query structural sharing).
  const agents = useMemo(
    () => buildSourceCollectionStageAgentCards({
      stageId,
      bindings,
      lang,
      agentSummaryPending,
      agentSummaryFetching,
      agentSummaryError,
      teamId,
      returnTo,
    }),
    [
      stageId,
      bindings,
      lang,
      agentSummaryPending,
      agentSummaryFetching,
      agentSummaryError,
      teamId,
      returnTo,
    ],
  );
  if (!bindings.length) {
    return null;
  }
  return <TeamSourceCollectionStageAgentsPanel lang={lang} agents={agents} />;
}
