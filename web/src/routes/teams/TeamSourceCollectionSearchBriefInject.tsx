/**
 * SC inject claim: search-brief configuration surface (workspace: SC controls / finding).
 * Owns draft presentation only; flow progression lives on the right-rail stage primary.
 */
import type { ReactNode } from "react";

import { TeamSourceCollectionSearchBriefPanel } from "./teamLazyPanels";
import type { SourceCollectionDraft } from "./source-collection/presentationModel";

export type TeamSourceCollectionSearchBriefInjectProps = {
  lang: "zh" | "en";
  draft: SourceCollectionDraft;
  modeFields: ReactNode;
  hasExistingRun: boolean;
  onDraftChange: (patch: Partial<SourceCollectionDraft>) => void;
};

export function TeamSourceCollectionSearchBriefInject({
  lang,
  draft,
  modeFields,
  hasExistingRun,
  onDraftChange,
}: TeamSourceCollectionSearchBriefInjectProps) {
  return (
    <TeamSourceCollectionSearchBriefPanel
      lang={lang}
      draft={draft}
      modeFields={modeFields}
      hasExistingRun={hasExistingRun}
      onDraftChange={onDraftChange}
    />
  );
}
