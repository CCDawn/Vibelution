/**
 * F3 — pure count/label helpers for source-collection presentation.
 */
import { sourceCollectionStableCountText } from "./runModel";

export type SourceCollectionCountTextOptions = {
  lang: "zh" | "en";
  loadingText: string;
  syncingText: string;
};

export function makeSourceCollectionCountText(options: SourceCollectionCountTextOptions) {
  const { lang, loadingText, syncingText } = options;
  const countText = (loading: boolean, value: number) =>
    sourceCollectionStableCountText({
      loading,
      value,
      lang,
      loadingText,
      syncingText,
    });
  const countWithUnit = (loading: boolean, value: number, zhUnit: string, enUnit = "") =>
    sourceCollectionStableCountText({
      loading,
      value,
      lang,
      zhUnit,
      enUnit,
      loadingText,
      syncingText,
    });
  return { countText, countWithUnit };
}
