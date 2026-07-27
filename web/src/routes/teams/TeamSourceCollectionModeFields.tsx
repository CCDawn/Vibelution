/**
 * SC inject surface: collection mode + local roots fields (workspace claim).
 * Stays free of TeamsRoute query/mutation ownership.
 */
import { VNativeInput, VNativeSelect } from "../../components/vui";
import {
  shouldShowLocalScanRootsField,
  sourceCollectionModeFieldOptions,
  sourceCollectionModeFieldsVisible,
} from "./source-collection/injectModel";
import {
  sourceCollectionCollectionModeLabel,
  type SourceCollectionDraft,
  type SourceCollectionMode,
} from "./source-collection/presentationModel";

export type TeamSourceCollectionModeFieldsDraft = Pick<
  SourceCollectionDraft,
  "collectionMode" | "localScanRoots"
>;

export type TeamSourceCollectionModeFieldsProps = {
  lang: "zh" | "en";
  knowledgeExpansionWorkflowTeamSelected: boolean;
  draft: TeamSourceCollectionModeFieldsDraft;
  localScanDefaultRoots: string;
  onDraftChange: (patch: Partial<TeamSourceCollectionModeFieldsDraft>) => void;
};

export function TeamSourceCollectionModeFields({
  lang,
  knowledgeExpansionWorkflowTeamSelected,
  draft,
  localScanDefaultRoots,
  onDraftChange,
}: TeamSourceCollectionModeFieldsProps) {
  if (!sourceCollectionModeFieldsVisible(knowledgeExpansionWorkflowTeamSelected)) {
    return null;
  }
  const mode = draft.collectionMode || "mixed";
  const modeOptions = sourceCollectionModeFieldOptions(lang, sourceCollectionCollectionModeLabel);
  return (
    <>
      <label>
        <span>{lang === "zh" ? "来源模式" : "Source mode"}</span>
        <VNativeSelect
          value={mode}
          onChange={(event) =>
            onDraftChange({
              collectionMode: event.target.value as SourceCollectionMode,
            })
          }
        >
          {modeOptions.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </VNativeSelect>
      </label>
      {shouldShowLocalScanRootsField(mode) ? (
        <label>
          <span>{lang === "zh" ? "本地根目录" : "Local roots"}</span>
          <VNativeInput
            value={draft.localScanRoots ?? ""}
            onChange={(event) => onDraftChange({ localScanRoots: event.target.value })}
            placeholder={localScanDefaultRoots}
          />
        </label>
      ) : null}
    </>
  );
}
