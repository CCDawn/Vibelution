/**
 * Pure bag builder for lazy SC composition input (Wave 2).
 * Keeps foundation free of SC field-list churn.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */

export function buildTeamsScLayerInput(parts: {
  sourceCollectionWorkspace: Record<string, any>;
  mutationBundle: Record<string, any>;
  shell: Record<string, any>;
}): Record<string, any> {
  const { sourceCollectionWorkspace, mutationBundle, shell } = parts;
  return {
    sourceCollectionWorkspace,
    mutationBundle,
    ...shell,
  };
}
