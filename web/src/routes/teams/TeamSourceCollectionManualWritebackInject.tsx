/**
 * SC inject claim: manual writeback surface wiring (workspace: SC controls / writeback).
 * Owns assignment option building + submit gates; route only supplies mutation/state.
 */
import type { FormEvent } from "react";

import {
  TeamSourceCollectionManualWritebackPanel,
  type TeamSourceCollectionManualWritebackDraft,
} from "../TeamSourceCollectionManualWritebackPanel";
import {
  buildSourceCollectionManualWritebackAssignmentOptions,
  canSubmitSourceCollectionManualWriteback,
  resolveSourceCollectionManualWritebackAssignmentValue,
  type SourceCollectionAssignmentLike,
} from "./source-collection/injectModel";

export type TeamSourceCollectionManualWritebackInjectProps = {
  lang: "zh" | "en";
  draft: TeamSourceCollectionManualWritebackDraft;
  assignments: SourceCollectionAssignmentLike[];
  selectedAssignmentId?: string;
  sourceTypes?: string[];
  canSubmit: boolean;
  pending: boolean;
  teamId?: string;
  runId?: string;
  hasRecord: boolean;
  onDraftChange: (patch: Partial<TeamSourceCollectionManualWritebackDraft>) => void;
  onSubmitRecord: (input: {
    teamId: string;
    runId: string;
    draft: TeamSourceCollectionManualWritebackDraft & { assignmentId: string };
  }) => void;
  sourceTypeLabel: (sourceType: string) => string;
  title?: string;
  description?: string;
  wrapInDetails?: boolean;
};

const DEFAULT_SOURCE_TYPES = ["paper", "url", "dataset", "file", "note", "manual"];

export function TeamSourceCollectionManualWritebackInject({
  lang,
  draft,
  assignments,
  selectedAssignmentId,
  sourceTypes = DEFAULT_SOURCE_TYPES,
  canSubmit,
  pending,
  teamId,
  runId,
  hasRecord,
  onDraftChange,
  onSubmitRecord,
  sourceTypeLabel,
  title,
  description,
  wrapInDetails,
}: TeamSourceCollectionManualWritebackInjectProps) {
  const assignmentValue = resolveSourceCollectionManualWritebackAssignmentValue(
    draft.assignmentId,
    selectedAssignmentId,
  );
  return (
    <TeamSourceCollectionManualWritebackPanel
      lang={lang}
      draft={draft}
      assignmentValue={assignmentValue}
      assignments={buildSourceCollectionManualWritebackAssignmentOptions(assignments, lang)}
      sourceTypes={sourceTypes}
      canSubmit={canSubmit}
      pending={pending}
      onDraftChange={onDraftChange}
      onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const assignmentId = resolveSourceCollectionManualWritebackAssignmentValue(
          draft.assignmentId,
          selectedAssignmentId,
        );
        if (!canSubmitSourceCollectionManualWriteback({
          teamId,
          runId,
          assignmentId,
          hasRecord,
        })) {
          return;
        }
        onSubmitRecord({
          teamId: String(teamId),
          runId: String(runId),
          draft: { ...draft, assignmentId },
        });
      }}
      sourceTypeLabel={sourceTypeLabel}
      title={title}
      description={description}
      wrapInDetails={wrapInDetails}
    />
  );
}
