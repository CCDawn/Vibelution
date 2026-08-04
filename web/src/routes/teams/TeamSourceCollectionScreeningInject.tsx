/**
 * SC inject: screening workspace + recommended-next-hint presentation.
 */
import {
  TeamSourceCollectionScreeningWorkspacePanel,
  type TeamSourceCollectionScreeningWorkspacePanelProps,
} from "../TeamSourceCollectionScreeningWorkspacePanel";
import { resolveSourceCollectionScreeningRecommendedNextHint } from "./source-collection/injectModel";

export type TeamSourceCollectionScreeningInjectProps = Omit<
  TeamSourceCollectionScreeningWorkspacePanelProps,
  "sourceCollectionRecommendedNextHint" | "sourceCollectionQualityReviewIsSecondary"
> & {
  needsAgentMaterial: boolean;
  pendingScreeningCount: number;
  projectedApprovedCount: number;
};

export function TeamSourceCollectionScreeningInject({
  needsAgentMaterial,
  pendingScreeningCount,
  projectedApprovedCount,
  ...panelProps
}: TeamSourceCollectionScreeningInjectProps) {
  const recommendedNextHint = resolveSourceCollectionScreeningRecommendedNextHint({
    lang: panelProps.lang,
    needsAgentMaterial,
    pendingScreeningCount,
    projectedApprovedCount,
    screeningButtonText: panelProps.sourceCollectionScreeningButtonText,
  });

  return (
    <TeamSourceCollectionScreeningWorkspacePanel
      {...panelProps}
      sourceCollectionQualityReviewIsSecondary={needsAgentMaterial}
      sourceCollectionRecommendedNextHint={recommendedNextHint}
    />
  );
}
