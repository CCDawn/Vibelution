import { VButton, VInput, VSurface } from "../../../components/vui";

import {
  createResearchRunSafetyBudget,
  matchingResearchRunSafetyPreset,
  RESEARCH_RUN_SAFETY_PRESETS,
  type ResearchRunSafetyBudget,
  type ResearchRunSafetyPresetId,
  type ResearchRunSafetyStageId,
  totalResearchRunSafetyTokens,
} from "./researchRunSafetyBudget";
import styles from "./ResearchRunSafetyLimitPanel.styles";

const STAGES: Array<{ id: ResearchRunSafetyStageId; label: string }> = [
  { id: "knowledge_collection", label: "知识搜集" },
  { id: "experiment_design", label: "实验设计" },
  { id: "execution_iteration", label: "执行迭代" },
];

function formatInteger(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatDuration(seconds: number): string {
  return `${Math.round(seconds / 3600)} 小时`;
}

function nextPositiveInteger(value: string): number | null {
  const next = Number(value);
  return Number.isInteger(next) && next > 0 ? next : null;
}

export function ResearchRunSafetyLimitPanel(props: {
  budget: ResearchRunSafetyBudget;
  isDisabled?: boolean;
  onChange: (budget: ResearchRunSafetyBudget) => void;
}) {
  const { budget, isDisabled = false, onChange } = props;
  const activePreset = matchingResearchRunSafetyPreset(budget);
  const totalTokens = totalResearchRunSafetyTokens(budget);
  const update = (patch: Partial<ResearchRunSafetyBudget>) => onChange({ ...budget, ...patch });
  const updateStageTokens = (stageId: ResearchRunSafetyStageId, value: string) => {
    const tokens = nextPositiveInteger(value);
    if (tokens === null) return;
    update({ stageTokens: { ...budget.stageTokens, [stageId]: tokens } });
  };
  const updateLimit = (key: "toolCalls" | "wallClockSeconds" | "maxRetries", value: string) => {
    const limit = nextPositiveInteger(value);
    if (limit !== null) update({ [key]: limit });
  };
  const updateWallClockHours = (value: string) => {
    const hours = nextPositiveInteger(value);
    if (hours !== null) update({ wallClockSeconds: hours * 3600 });
  };

  return (
    <VSurface tone="inset" padding="compact" className={styles.root} ariaLabel="运行安全上限">
      <div className={styles.header}>
        <h4 className={styles.title}>运行安全上限</h4>
        <span className={styles.total}>{formatInteger(totalTokens)} tokens</span>
      </div>
      <div className={styles.presets} role="group" aria-label="运行安全上限预设">
        {(Object.keys(RESEARCH_RUN_SAFETY_PRESETS) as ResearchRunSafetyPresetId[]).map((presetId) => (
          <VButton
            key={presetId}
            type="button"
            variant={activePreset === presetId ? "primary" : "secondary"}
            density="compact"
            aria-pressed={activePreset === presetId}
            isDisabled={isDisabled}
            className={styles.preset}
            onClick={() => onChange(createResearchRunSafetyBudget(presetId))}
          >
            {RESEARCH_RUN_SAFETY_PRESETS[presetId].label}
          </VButton>
        ))}
      </div>
      <div className={styles.stages}>
        {STAGES.map((stage) => (
          <label key={stage.id} className={styles.stage}>
            <span className={styles.stageName}>{stage.label}</span>
            <VInput
              aria-label={`${stage.label} 阶段 token 上限`}
              type="number"
              min={1}
              step={1000}
              value={String(budget.stageTokens[stage.id])}
              onChange={(event) => updateStageTokens(stage.id, event.currentTarget.value)}
              isDisabled={isDisabled}
              className={styles.stageInput}
            />
          </label>
        ))}
      </div>
      <div className={styles.summary}>
        三阶段合计 · {formatDuration(budget.wallClockSeconds)} · {formatInteger(budget.toolCalls)} 次调用 · {budget.maxRetries} 次重试
      </div>
      <div className={styles.advanced}>
        <label className={styles.advancedField}>
          工具调用上限
          <VInput
            aria-label="工具调用上限"
            type="number"
            min={1}
            value={String(budget.toolCalls)}
            onChange={(event) => updateLimit("toolCalls", event.currentTarget.value)}
            isDisabled={isDisabled}
            className={styles.advancedInput}
          />
        </label>
        <label className={styles.advancedField}>
          运行时间（小时）
          <VInput
            aria-label="运行时间上限（小时）"
            type="number"
            min={1}
            step={1}
            value={String(Math.round(budget.wallClockSeconds / 3600))}
            onChange={(event) => updateWallClockHours(event.currentTarget.value)}
            isDisabled={isDisabled}
            className={styles.advancedInput}
          />
        </label>
        <label className={styles.advancedField}>
          节点重试次数
          <VInput
            aria-label="节点重试次数"
            type="number"
            min={1}
            value={String(budget.maxRetries)}
            onChange={(event) => updateLimit("maxRetries", event.currentTarget.value)}
            isDisabled={isDisabled}
            className={styles.advancedInput}
          />
        </label>
      </div>
    </VSurface>
  );
}
