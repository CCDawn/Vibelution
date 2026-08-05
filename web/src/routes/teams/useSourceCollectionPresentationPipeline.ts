/** SC presentation pipeline orchestrator (R2-s close-out). */
import type { UseSourceCollectionPresentationInput } from "./useSourceCollectionPresentationTypes";
import { useSourceCollectionPresentationMid } from "./useSourceCollectionPresentationMid";
import { useSourceCollectionPresentationTail } from "./useSourceCollectionPresentationTail";

export type { UseSourceCollectionPresentationInput } from "./useSourceCollectionPresentationTypes";

export function useSourceCollectionPresentationPipeline(input: UseSourceCollectionPresentationInput) {
  const mid = useSourceCollectionPresentationMid(input);
  return useSourceCollectionPresentationTail(input, mid);
}
