import { Search } from "lucide-react";
import { type ReactNode } from "react";

import { VNativeButton, VNativeInput, VNativeTextarea } from "../components/vui";
import styles from "./TeamSourceCollectionRunSettingsPanel.styles";

export type TeamSourceCollectionRunSettingsDraft = {
  title: string;
  topic: string;
  goal: string;
  querySeeds: string;
  inputRefs: string;
  searchLanguages: string;
  sourceTypes: string;
  maxResultsPerQuery: number;
};

type TeamSourceCollectionRunSettingsLang = "zh" | "en";

type TeamSourceCollectionRunSettingsPanelProps = {
  lang: TeamSourceCollectionRunSettingsLang;
  draft: TeamSourceCollectionRunSettingsDraft;
  modeFields: ReactNode;
  open: boolean;
  canStart: boolean;
  startPending: boolean;
  onDraftChange: (patch: Partial<TeamSourceCollectionRunSettingsDraft>) => void;
  onSubmit: () => void;
};

export function TeamSourceCollectionRunSettingsPanel({
  lang,
  draft,
  modeFields,
  open,
  canStart,
  startPending,
  onDraftChange,
  onSubmit,
}: TeamSourceCollectionRunSettingsPanelProps) {
  const isZh = lang === "zh";

  return (
    <details className={styles.workflowSourceCollectionDetails} open={open}>
      <summary>
        <span>{isZh ? "本轮配置" : "Run settings"}</span>
      </summary>
      <form
        className={styles.workflowSourceCollectionForm}
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <label>
          <span>{isZh ? "主题" : "Topic"}</span>
          <VNativeInput
            value={draft.topic}
            onChange={(event) => onDraftChange({ topic: event.target.value })}
          />
        </label>
        <label>
          <span>{isZh ? "标题" : "Title"}</span>
          <VNativeInput
            value={draft.title}
            onChange={(event) => onDraftChange({ title: event.target.value })}
          />
        </label>
        <label className={styles.workflowSourceCollectionWide}>
          <span>{isZh ? "目标" : "Goal"}</span>
          <VNativeTextarea
            value={draft.goal}
            onChange={(event) => onDraftChange({ goal: event.target.value })}
            rows={2}
          />
        </label>
        <label>
          <span>{isZh ? "搜索种子" : "Query seeds"}</span>
          <VNativeTextarea
            value={draft.querySeeds}
            onChange={(event) => onDraftChange({ querySeeds: event.target.value })}
            rows={3}
          />
        </label>
        <label>
          <span>{isZh ? "输入引用" : "Input refs"}</span>
          <VNativeTextarea
            value={draft.inputRefs}
            onChange={(event) => onDraftChange({ inputRefs: event.target.value })}
            rows={3}
            placeholder={isZh ? "可选：本地文件、seed-query:..." : "Optional: local file, seed-query:..."}
          />
        </label>
        {modeFields}
        <label>
          <span>{isZh ? "语言" : "Languages"}</span>
          <VNativeInput
            value={draft.searchLanguages}
            onChange={(event) => onDraftChange({ searchLanguages: event.target.value })}
          />
        </label>
        <label>
          <span>{isZh ? "资料类型" : "Source types"}</span>
          <VNativeInput
            value={draft.sourceTypes}
            onChange={(event) => onDraftChange({ sourceTypes: event.target.value })}
          />
        </label>
        <label>
          <span>{isZh ? "每条上限" : "Max results"}</span>
          <VNativeInput
            type="number"
            min={1}
            max={100}
            value={draft.maxResultsPerQuery}
            onChange={(event) =>
              onDraftChange({
                maxResultsPerQuery: Math.max(1, Math.min(100, Number(event.target.value) || 1)),
              })
            }
          />
        </label>
        <VNativeButton type="submit" disabled={!canStart || startPending}>
          <Search size={13} />
          {startPending
            ? (isZh ? "启动中" : "Starting")
            : (isZh ? "启动搜集批次" : "Start collection")}
        </VNativeButton>
      </form>
    </details>
  );
}
