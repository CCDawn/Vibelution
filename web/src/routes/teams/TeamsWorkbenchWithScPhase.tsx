/**
 * Secondary-lazy SC + shell phase host.
 * Loaded as a separate chunk so Mid/Tail presentation + compose/inject leave the
 * eager TeamsRoute/foundation graph.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import type { ReactNode } from "react";

import { useTeamsWorkbenchScLayer } from "./useTeamsWorkbenchScLayer";
import { useTeamsWorkbenchShellPhase } from "./useTeamsWorkbenchShellPhase";

export type TeamsWorkbenchWithScPhaseProps = {
  /** Foundation bag without SC composition fields (includes scLayerInput + launch guard ref). */
  base: Record<string, any>;
};

export function TeamsWorkbenchWithScPhase({ base }: TeamsWorkbenchWithScPhaseProps): ReactNode {
  const scLayerInput = base.scLayerInput ?? base;
  const scLayer = useTeamsWorkbenchScLayer(scLayerInput);

  const researchLaunchGuardRef = base.researchLaunchGuardRef as
    | { current: { startPending: boolean; canLaunch: boolean } }
    | undefined;
  if (researchLaunchGuardRef) {
    researchLaunchGuardRef.current = {
      startPending: Boolean(scLayer.selectedTeamStartResearchStagePendingFromSc),
      canLaunch: scLayer.researchStageCanLaunchFromSc !== false,
    };
  }

  const bag = {
    ...base,
    ...scLayer,
    selectedTeamStartResearchStagePending: scLayer.selectedTeamStartResearchStagePendingFromSc,
    researchStageCanLaunch: scLayer.researchStageCanLaunchFromSc,
  };

  return useTeamsWorkbenchShellPhase(bag);
}
