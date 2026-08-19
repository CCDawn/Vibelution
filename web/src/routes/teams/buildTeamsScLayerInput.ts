/**
 * Pure bag builder for lazy SC composition input (Wave 2).
 * Keeps foundation free of SC field-list churn.
 */
import type { useSourceCollectionWorkspace } from "./useSourceCollectionWorkspace";
import type { useTeamsMutationBundle } from "./useTeamsMutationBundle";

export function buildTeamsScLayerInput(parts: {
  sourceCollectionWorkspace: ReturnType<typeof useSourceCollectionWorkspace>;
  mutationBundle: ReturnType<typeof useTeamsMutationBundle>;
  // Foundation shell subset boundary: the 328-field workbench bag stays any until Phase 9+ foundation typing.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  shell: Record<string, any>;
}): {
  sourceCollectionWorkspace: ReturnType<typeof useSourceCollectionWorkspace>;
  mutationBundle: ReturnType<typeof useTeamsMutationBundle>;
  // Spread shell keys land on this index signature (TS drops index signatures on object spread).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
} {
  const { sourceCollectionWorkspace, mutationBundle, shell } = parts;
  return {
    sourceCollectionWorkspace,
    mutationBundle,
    ...shell,
  };
}
