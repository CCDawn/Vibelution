import type {
  ConfigMigrationArtifactConflict,
  ConfigMigrationArtifactResolution,
  ConfigMigrationArtifactResolutionDecision,
} from "../api/types";

export type ConfigMigrationResolutionDraft = {
  modelId: string;
  allowedResolutions: ConfigMigrationArtifactResolutionDecision[];
  decision: ConfigMigrationArtifactResolutionDecision | "";
  preserveConfirmed: boolean;
  upstreamId: string;
};

export type ConfigMigrationResolutionDraftPatch = Partial<
  Pick<ConfigMigrationResolutionDraft, "decision" | "preserveConfirmed" | "upstreamId">
>;

export function createArtifactResolutionDrafts(
  conflicts: readonly ConfigMigrationArtifactConflict[],
): ConfigMigrationResolutionDraft[] {
  const seenModelIds = new Set<string>();
  const drafts: ConfigMigrationResolutionDraft[] = [];

  for (const conflict of conflicts) {
    const modelId = conflict.modelId.trim();
    if (!modelId || seenModelIds.has(modelId)) continue;
    seenModelIds.add(modelId);
    drafts.push({
      modelId,
      allowedResolutions: [...new Set(conflict.allowedResolutions)],
      decision: "",
      preserveConfirmed: false,
      upstreamId: "",
    });
  }

  return drafts;
}

export function updateArtifactResolutionDraft(
  drafts: readonly ConfigMigrationResolutionDraft[],
  modelId: string,
  patch: ConfigMigrationResolutionDraftPatch,
): ConfigMigrationResolutionDraft[] {
  return drafts.map((draft) => {
    if (draft.modelId !== modelId) return draft;
    if (
      patch.decision
      && !draft.allowedResolutions.includes(patch.decision)
    ) {
      return draft;
    }
    return { ...draft, ...patch };
  });
}

export function isValidSplitUpstreamId(value: string): boolean {
  const upstreamId = value.trim();
  if (!upstreamId || /\s/.test(upstreamId)) return false;
  if (/^(?:\.\.?[\\/]|[\\/~]|[a-zA-Z]:[\\/]|file:)/i.test(upstreamId)) return false;
  if (/\.(?:gguf|safetensors|bin)$/i.test(upstreamId)) return false;
  return true;
}

export function buildArtifactResolutions(
  drafts: readonly ConfigMigrationResolutionDraft[],
): ConfigMigrationArtifactResolution[] | null {
  if (!drafts.length) return null;
  const resolutions: ConfigMigrationArtifactResolution[] = [];
  const seenModelIds = new Set<string>();

  for (const draft of drafts) {
    if (seenModelIds.has(draft.modelId)) continue;
    seenModelIds.add(draft.modelId);
    if (!draft.decision || !draft.allowedResolutions.includes(draft.decision)) return null;
    if (draft.decision === "preserve_upstream_id") {
      if (!draft.preserveConfirmed) return null;
      resolutions.push({ modelId: draft.modelId, decision: draft.decision });
      continue;
    }
    if (!isValidSplitUpstreamId(draft.upstreamId)) return null;
    resolutions.push({
      modelId: draft.modelId,
      decision: draft.decision,
      upstreamId: draft.upstreamId.trim(),
    });
  }

  return resolutions;
}
