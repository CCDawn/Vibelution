import { CheckCircle2 } from "lucide-react";
import { type FormEvent } from "react";

import { VNativeButton, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
import styles from "./TeamsRoute.styles";

export type TeamSourceCollectionManualWritebackAssignment = {
  id: string;
  label: string;
};

export type TeamSourceCollectionManualWritebackDraft = {
  assignmentId: string;
  sourceType: string;
  title: string;
  sourceRef: string;
  rawLocation: string;
  summary: string;
  notes: string;
};

type TeamSourceCollectionManualWritebackPanelProps = {
  lang: "zh" | "en";
  draft: TeamSourceCollectionManualWritebackDraft;
  assignmentValue: string;
  assignments: TeamSourceCollectionManualWritebackAssignment[];
  sourceTypes: string[];
  canSubmit: boolean;
  pending: boolean;
  onDraftChange: (patch: Partial<TeamSourceCollectionManualWritebackDraft>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  sourceTypeLabel: (sourceType: string) => string;
  title?: string;
  description?: string;
  wrapInDetails?: boolean;
};

export function TeamSourceCollectionManualWritebackPanel({
  lang,
  draft,
  assignmentValue,
  assignments,
  sourceTypes,
  canSubmit,
  pending,
  onDraftChange,
  onSubmit,
  sourceTypeLabel,
  title,
  description,
  wrapInDetails = true,
}: TeamSourceCollectionManualWritebackPanelProps) {
  const isZh = lang === "zh";
  const headerTitle = title ?? (isZh ? "写入一条资料结果" : "Write one collected source");
  const headerDescription =
    description ?? (isZh ? "生成资料记录后自动导入候选资料库" : "Creates a DataRecord, then imports a source_manifest candidate");

  const form = (
    <form className={styles.workflowSourceCollectionOutputForm} onSubmit={onSubmit}>
      <div className={styles.workflowSourceCollectionOutputHeader}>
        <strong>{headerTitle}</strong>
        <span>{headerDescription}</span>
      </div>
      <label>
        <span>{isZh ? "分工任务" : "Assignment"}</span>
        <VNativeSelect
          value={assignmentValue}
          onChange={(event) => onDraftChange({ assignmentId: event.target.value })}
          disabled={!assignments.length}
        >
          {assignments.map((assignment) => (
            <option key={assignment.id} value={assignment.id}>
              {assignment.label}
            </option>
          ))}
        </VNativeSelect>
      </label>
      <label>
        <span>{isZh ? "类型" : "Type"}</span>
        <VNativeSelect value={draft.sourceType} onChange={(event) => onDraftChange({ sourceType: event.target.value })}>
          {sourceTypes.map((sourceType) => (
            <option key={sourceType} value={sourceType}>
              {sourceTypeLabel(sourceType)}
            </option>
          ))}
        </VNativeSelect>
      </label>
      <label>
        <span>{isZh ? "标题" : "Title"}</span>
        <VNativeInput value={draft.title} onChange={(event) => onDraftChange({ title: event.target.value })} />
      </label>
      <label>
        <span>{isZh ? "来源引用" : "Source ref"}</span>
        <VNativeInput
          value={draft.sourceRef}
          onChange={(event) => onDraftChange({ sourceRef: event.target.value })}
          placeholder="https://doi.org/... / local path / dataset id"
        />
      </label>
      <label>
        <span>{isZh ? "原始位置" : "Raw location"}</span>
        <VNativeInput
          value={draft.rawLocation}
          onChange={(event) => onDraftChange({ rawLocation: event.target.value })}
          placeholder={isZh ? "页码、文件路径、段落或采集位置" : "Page range, file path, section, or capture location"}
        />
      </label>
      <label className={styles.workflowSourceCollectionWide}>
        <span>{isZh ? "摘要" : "Summary"}</span>
        <VNativeTextarea value={draft.summary} onChange={(event) => onDraftChange({ summary: event.target.value })} rows={2} />
      </label>
      <label className={styles.workflowSourceCollectionWide}>
        <span>{isZh ? "备注" : "Notes"}</span>
        <VNativeInput value={draft.notes} onChange={(event) => onDraftChange({ notes: event.target.value })} />
      </label>
      <VNativeButton type="submit" disabled={!canSubmit}>
        <CheckCircle2 size={13} />
        {pending ? (isZh ? "回写中" : "Writing") : isZh ? "回写并导入候选" : "Write back and import"}
      </VNativeButton>
    </form>
  );

  if (!wrapInDetails) {
    return form;
  }

  return (
    <details className={styles.workflowSourceCollectionDetails}>
      <summary>
        <span>{isZh ? "兜底手工回写" : "Fallback manual writeback"}</span>
      </summary>
      {form}
    </details>
  );
}
