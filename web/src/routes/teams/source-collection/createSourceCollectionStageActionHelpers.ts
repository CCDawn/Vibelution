/**
 * Stage task action label/readiness helpers for SC presentation.
 * Phase R2-o extract from useSourceCollectionPresentationCore (behavior-conserving).
 */
import {
  sourceCollectionStageBackendActionReadiness,
  type SourceCollectionActionReadiness,
  type SourceCollectionStageCardProjection,
  type SourceCollectionStageModuleId,
} from "./stageProjection";

export type CreateSourceCollectionStageActionHelpersInput = {
  lang: "zh" | "en";
  sourceCollectionStageSessionTaskPendingStageId: SourceCollectionStageModuleId | string | null | undefined;
  sourceCollectionStageLaunchActive: (stageId: SourceCollectionStageModuleId) => boolean;
  sourceCollectionActionReadiness: (
    disabled: boolean,
    reason: string,
    loading?: boolean,
  ) => SourceCollectionActionReadiness;
  selectedTeamStartSourceCollectionStageTaskPending: boolean;
  sourceCollectionActionBusyReason: string;
  sourceCollectionStageCardById: Map<SourceCollectionStageModuleId, SourceCollectionStageCardProjection | null | undefined>;
  sourceCollectionCollectionActionReadiness: SourceCollectionActionReadiness;
  sourceCollectionActionNoInputReason: string;
  sourceCollectionCandidateExtractionActionReadiness: SourceCollectionActionReadiness;
  sourceCollectionScreeningActionReadiness: SourceCollectionActionReadiness;
  sourceCollectionGraphActionReadiness: SourceCollectionActionReadiness;
  sourceCollectionMemoryActionReadiness: SourceCollectionActionReadiness;
};

export function createSourceCollectionStageActionHelpers(
  input: CreateSourceCollectionStageActionHelpersInput,
) {
  const {
    lang,
    sourceCollectionStageSessionTaskPendingStageId,
    sourceCollectionStageLaunchActive,
    sourceCollectionActionReadiness,
    selectedTeamStartSourceCollectionStageTaskPending,
    sourceCollectionActionBusyReason,
    sourceCollectionStageCardById,
    sourceCollectionCollectionActionReadiness,
    sourceCollectionActionNoInputReason,
    sourceCollectionCandidateExtractionActionReadiness,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionGraphActionReadiness,
    sourceCollectionMemoryActionReadiness,
  } = input;

  const sourceCollectionStageTaskActionLabel = (stageId: SourceCollectionStageModuleId, label: string) =>
    sourceCollectionStageSessionTaskPendingStageId === stageId
      ? (lang === "zh" ? "启动 Agent 中" : "Starting Agent")
      : sourceCollectionStageLaunchActive(stageId)
        ? (lang === "zh" ? "等待 Agent 回写" : "Waiting for Agent writeback")
        : label;

  const sourceCollectionStageTaskActionReadiness = (
    stageId: SourceCollectionStageModuleId,
    readiness: SourceCollectionActionReadiness,
  ) =>
    sourceCollectionStageLaunchActive(stageId)
      ? sourceCollectionActionReadiness(true, lang === "zh" ? "等待 Agent 回写" : "Waiting for Agent writeback", true)
      : readiness.disabled
        ? readiness
        : sourceCollectionActionReadiness(
            selectedTeamStartSourceCollectionStageTaskPending,
            sourceCollectionActionBusyReason,
            selectedTeamStartSourceCollectionStageTaskPending,
          );

  const sourceCollectionStageActionLabelFor = (stageId: SourceCollectionStageModuleId, fallback: string) =>
    sourceCollectionStageTaskActionLabel(
      stageId,
      sourceCollectionStageCardById.get(stageId)?.actionReadiness?.actionLabel || fallback,
    );

  const sourceCollectionStageActionReadinessFor = (
    stageId: SourceCollectionStageModuleId,
  ): SourceCollectionActionReadiness => {
    if (stageId === "finding") {
      return sourceCollectionStageTaskActionReadiness(
        "finding",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("finding"),
          sourceCollectionCollectionActionReadiness,
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    if (stageId === "extraction") {
      const extractionDisabled =
        sourceCollectionCandidateExtractionActionReadiness.disabled
        && sourceCollectionScreeningActionReadiness.disabled;
      const extractionLoading =
        sourceCollectionCandidateExtractionActionReadiness.loading
        || sourceCollectionScreeningActionReadiness.loading;
      const extractionReason = !sourceCollectionCandidateExtractionActionReadiness.disabled
        ? sourceCollectionCandidateExtractionActionReadiness.reason
        : sourceCollectionScreeningActionReadiness.reason
          || sourceCollectionCandidateExtractionActionReadiness.reason;
      return sourceCollectionStageTaskActionReadiness(
        "extraction",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("extraction"),
          sourceCollectionActionReadiness(
            extractionDisabled,
            extractionReason || sourceCollectionActionNoInputReason,
            extractionLoading,
          ),
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    if (stageId === "relations") {
      return sourceCollectionStageTaskActionReadiness(
        "relations",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("relations"),
          sourceCollectionGraphActionReadiness,
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    return sourceCollectionStageTaskActionReadiness(
      "ingestion",
      sourceCollectionStageBackendActionReadiness(
        sourceCollectionStageCardById.get("ingestion"),
        sourceCollectionMemoryActionReadiness,
        sourceCollectionActionNoInputReason,
      ),
    );
  };

  return {
    sourceCollectionStageTaskActionLabel,
    sourceCollectionStageTaskActionReadiness,
    sourceCollectionStageActionLabelFor,
    sourceCollectionStageActionReadinessFor,
  };
}
