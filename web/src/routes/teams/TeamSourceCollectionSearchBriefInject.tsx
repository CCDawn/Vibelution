/**
 * SC inject claim: search-brief start surface wiring (workspace: SC controls / finding).
 * Owns submit gate pure checks; route only supplies mutation/state.
 */
import type { ReactNode } from "react";

import { TeamSourceCollectionSearchBriefPanel } from "../TeamSourceCollectionSearchBriefPanel";
import type { SourceCollectionDraft } from "./source-collection/presentationModel";
import { canStartSourceCollectionRun } from "./source-collection/injectModel";

export type TeamSourceCollectionSearchBriefInjectProps = {
  lang: "zh" | "en";
  draft: SourceCollectionDraft;
  modeFields: ReactNode;
  hasExistingRun: boolean;
  canStart: boolean;
  startPending: boolean;
  teamId?: string;
  onDraftChange: (patch: Partial<SourceCollectionDraft>) => void;
  onStart: (input: { teamId: string; draft: SourceCollectionDraft }) => void;
};

export function TeamSourceCollectionSearchBriefInject({
  lang,
  draft,
  modeFields,
  hasExistingRun,
  canStart,
  startPending,
  teamId,
  onDraftChange,
  onStart,
}: TeamSourceCollectionSearchBriefInjectProps) {
  return (
    <TeamSourceCollectionSearchBriefPanel
      lang={lang}
      draft={draft}
      modeFields={modeFields}
      hasExistingRun={hasExistingRun}
      canStart={canStart}
      startPending={startPending}
      onDraftChange={onDraftChange}
      onSubmit={() => {
        if (!canStartSourceCollectionRun({ teamId, canStart, startPending })) {
          return;
        }
        onStart({ teamId: String(teamId), draft });
      }}
    />
  );
}
