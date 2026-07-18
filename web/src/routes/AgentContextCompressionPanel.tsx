import { ExternalLink } from "lucide-react";

import { VButton, VCheckbox, VFieldRow, VNativeInput, VNativeSelect, VTooltip } from "../components/vui";
import styles from "./AgentContextCompressionPanel.styles";

export type AgentContextCompressionPolicyDraft = {
  mode: "inherit" | "custom";
  enabled: boolean;
  maxTokenLimit: string;
  maxCompressionsPerSession: string;
  lightThreshold: string;
  standardThreshold: string;
  deepThreshold: string;
  emergencyThreshold: string;
  lightSummaryChars: string;
  standardSummaryChars: string;
  deepSummaryChars: string;
  emergencySummaryChars: string;
  keepAiMessages: string;
  preserveErrors: boolean;
  extractKeyDecisions: boolean;
};

export type AgentContextCompressionPanelCopy = {
  contextCompressionPolicy: string;
  contextCompressionInherit: string;
  contextCompressionCustom: string;
  contextCompressionEnabled: string;
  contextCompressionMaxTokenLimit: string;
  contextCompressionMaxCount: string;
  contextCompressionThresholds: string;
  contextCompressionSummaryChars: string;
  contextCompressionKeepAi: string;
  contextCompressionPreserveErrors: string;
  contextCompressionExtractDecisions: string;
};

type AgentContextCompressionPanelProps = {
  copy: AgentContextCompressionPanelCopy;
  lang: "zh" | "en";
  policy: AgentContextCompressionPolicyDraft;
  title: string;
  onPolicyChange: (patch: Partial<AgentContextCompressionPolicyDraft>) => void;
  onOpenContextConfig: () => void;
};

export function AgentContextCompressionPanel({
  copy,
  lang,
  policy,
  title,
  onPolicyChange,
  onOpenContextConfig,
}: AgentContextCompressionPanelProps) {
  const custom = policy.mode === "custom";

  return (
    <VTooltip content={title} width="wide">
      <section
        className={styles.fieldWide}
        tabIndex={0}
        aria-label={`${copy.contextCompressionPolicy} · ${title}`}
      >
        <span>{copy.contextCompressionPolicy}</span>
        <div className={styles.compressionPolicyGrid}>
        <VFieldRow label={copy.contextCompressionPolicy}>
          <VNativeSelect
            value={policy.mode}
            onChange={(event) => onPolicyChange({
              mode: event.target.value === "custom" ? "custom" : "inherit",
            })}
          >
            <option value="inherit">{copy.contextCompressionInherit}</option>
            <option value="custom">{copy.contextCompressionCustom}</option>
          </VNativeSelect>
        </VFieldRow>
        <VCheckbox
          isSelected={policy.enabled}
          isDisabled={!custom}
          onChange={(value) => onPolicyChange({ enabled: value })}
        >
          {copy.contextCompressionEnabled}
        </VCheckbox>
        <VFieldRow label={copy.contextCompressionMaxTokenLimit}>
          <VNativeInput
            type="number"
            min={1}
            value={policy.maxTokenLimit}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ maxTokenLimit: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={copy.contextCompressionMaxCount}>
          <VNativeInput
            type="number"
            min={0}
            value={policy.maxCompressionsPerSession}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ maxCompressionsPerSession: event.target.value })}
          />
        </VFieldRow>
      </div>
        <div className={styles.compressionPolicySubgrid}>
        <VFieldRow label={`${copy.contextCompressionThresholds} · ${lang === "zh" ? "轻量" : "Light"}`}>
          <VNativeInput
            type="number"
            min={1}
            max={100}
            value={policy.lightThreshold}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ lightThreshold: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={`${copy.contextCompressionThresholds} · ${lang === "zh" ? "标准" : "Standard"}`}>
          <VNativeInput
            type="number"
            min={1}
            max={100}
            value={policy.standardThreshold}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ standardThreshold: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={`${copy.contextCompressionThresholds} · ${lang === "zh" ? "深度" : "Deep"}`}>
          <VNativeInput
            type="number"
            min={1}
            max={100}
            value={policy.deepThreshold}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ deepThreshold: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={`${copy.contextCompressionThresholds} · ${lang === "zh" ? "紧急" : "Emergency"}`}>
          <VNativeInput
            type="number"
            min={1}
            max={100}
            value={policy.emergencyThreshold}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ emergencyThreshold: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={`${copy.contextCompressionSummaryChars} · ${lang === "zh" ? "轻量" : "Light"}`}>
          <VNativeInput
            type="number"
            min={1}
            value={policy.lightSummaryChars}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ lightSummaryChars: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={`${copy.contextCompressionSummaryChars} · ${lang === "zh" ? "标准" : "Standard"}`}>
          <VNativeInput
            type="number"
            min={1}
            value={policy.standardSummaryChars}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ standardSummaryChars: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={`${copy.contextCompressionSummaryChars} · ${lang === "zh" ? "深度" : "Deep"}`}>
          <VNativeInput
            type="number"
            min={1}
            value={policy.deepSummaryChars}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ deepSummaryChars: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={`${copy.contextCompressionSummaryChars} · ${lang === "zh" ? "紧急" : "Emergency"}`}>
          <VNativeInput
            type="number"
            min={1}
            value={policy.emergencySummaryChars}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ emergencySummaryChars: event.target.value })}
          />
        </VFieldRow>
      </div>
        <div className={styles.compressionPolicyFooter}>
        <VFieldRow label={copy.contextCompressionKeepAi}>
          <VNativeInput
            type="number"
            min={0}
            value={policy.keepAiMessages}
            disabled={!custom}
            onChange={(event) => onPolicyChange({ keepAiMessages: event.target.value })}
          />
        </VFieldRow>
        <VCheckbox
          isSelected={policy.preserveErrors}
          isDisabled={!custom}
          onChange={(value) => onPolicyChange({ preserveErrors: value })}
        >
          {copy.contextCompressionPreserveErrors}
        </VCheckbox>
        <VCheckbox
          isSelected={policy.extractKeyDecisions}
          isDisabled={!custom}
          onChange={(value) => onPolicyChange({ extractKeyDecisions: value })}
        >
          {copy.contextCompressionExtractDecisions}
        </VCheckbox>
      </div>
        <div className={styles.configDeepLinkRow}>
          <VButton
            type="button"
            variant="secondary"
            icon={<ExternalLink size={15} />}
            onPress={onOpenContextConfig}
          >
            {lang === "zh" ? "去上下文配置" : "Open context config"}
          </VButton>
        </div>
      </section>
    </VTooltip>
  );
}
