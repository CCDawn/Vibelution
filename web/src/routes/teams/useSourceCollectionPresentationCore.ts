/** Core presentation body (R3). Thin entry over pipeline. */
/**
 * Source-collection presentation + action adapters for Teams.
 * Implementation body: useSourceCollectionPresentationPipeline (R2-q split for <800 LOC core).
 */
import type { UseSourceCollectionPresentationInput } from "./useSourceCollectionPresentationTypes";
import { useSourceCollectionPresentationPipeline } from "./useSourceCollectionPresentationPipeline";

export type { UseSourceCollectionPresentationInput } from "./useSourceCollectionPresentationTypes";

export function useSourceCollectionPresentationCore(input: UseSourceCollectionPresentationInput) {
  return useSourceCollectionPresentationPipeline(input);
}

export type SourceCollectionPresentationApi = ReturnType<typeof useSourceCollectionPresentationCore>;
