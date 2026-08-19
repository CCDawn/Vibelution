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

const STAGES: Array<{ id: ResearchRunSafetyStageId; label: string; labelEn: string }> = [
  { id: "knowledge_collection", label: "知识搜集", labelEn: "Knowledge collection" },
  { id: "experiment_design", label: "实验设计", labelEn: "Experiment design" },
  { id: "execution_iteration", label: "执行迭代", labelEn: "Execution & iteration" },
];

const PRESET_LABEL_EN: Record<ResearchRunSafetyPresetId, string> = {
  steady: "Steady",
  recommended: "Recommended",
  extended: "Extended",
};

function formatInteger(value: number, isZh: boolean): string {
  return new Intl.NumberFormat(isZh ? "zh-CN" : "en-US").format(value);
}

function formatDuration(seconds: number, isZh: boolean): string {
  const hours = Math.round(seconds / 3600);
  return isZh ? `${hours} 小时` : `${hours} h`;
}

function nextPositiveInteger(value: string): number | null {
  const next = Number(value);
  return Number.isInteger(next) && next > 0 ? next : null;
}

export function ResearchRunSafetyLimitPanel(props: {
  budget: ResearchRunSafetyBudget;
  isDisabled?: boolean;
  onChange: (budget: ResearchRunSafetyBudget) => void;
  lang?: "zh" | "en";
}) {
  const { budget, isDisabled = false, onChange } = props;
  const isZh = props.lang !== "en";
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
    <VSurface tone="inset" padding="compact" className={styles.root} ariaLabel={isZh ? "运行安全上限" : "Run safety limits"}>
      <div className={styles.header}>
        <h4 className={styles.title}>{isZh ? "运行安全上限" : "Run safety limits"}</h4>
        <span className={styles.total}>{formatInteger(totalTokens, isZh)} tokens</span>
      </div>
      <div className={styles.presets} role="group" aria-label={isZh ? "运行安全上限预设" : "Run safety presets"}>
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
            {isZh ? RESEARCH_RUN_SAFETY_PRESETS[presetId].label : PRESET_LABEL_EN[presetId]}
          </VButton>
        ))}
      </div>
      <div className={styles.stages}>
        {STAGES.map((stage) => (
          <label key={stage.id} className={styles.stage}>
            <span className={styles.stageName}>{isZh ? stage.label : stage.labelEn}</span>
            <VInput
              aria-label={isZh ? `${stage.label} 阶段 token 上限` : `${stage.labelEn} stage token limit`}
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
        {isZh
          ? `三阶段合计 · ${formatDuration(budget.wallClockSeconds, isZh)} · ${formatInteger(budget.toolCalls, isZh)} 次调用 · ${budget.maxRetries} 次重试`
          : `Three-stage total · ${formatDuration(budget.wallClockSeconds, isZh)} · ${formatInteger(budget.toolCalls, isZh)} calls · ${budget.maxRetries} retries`}
      </div>
      <div className={styles.advanced}>
        <label className={styles.advancedField}>
          {isZh ? "工具调用上限" : "Tool call limit"}
          <VInput
            aria-label={isZh ? "工具调用上限" : "Tool call limit"}
            type="number"
            min={1}
            value={String(budget.toolCalls)}
            onChange={(event) => updateLimit("toolCalls", event.currentTarget.value)}
            isDisabled={isDisabled}
            className={styles.advancedInput}
          />
        </label>
        <label className={styles.advancedField}>
          {isZh ? "运行时间（小时）" : "Wall clock (hours)"}
          <VInput
            aria-label={isZh ? "运行时间上限（小时）" : "Wall clock limit (hours)"}
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
          {isZh ? "节点重试次数" : "Node retries"}
          <VInput
            aria-label={isZh ? "节点重试次数" : "Node retries"}
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
