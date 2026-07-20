import { CheckCircle2, CircleOff, Fingerprint } from "lucide-react";

import type { ConfigFeatureDecisionSnapshot } from "../api/types";
import { VSection, VStatusStrip } from "../components/vui";
import styles from "./ConfigFeatureDecisionPanel.styles";

type ConfigFeatureDecisionPanelProps = {
  snapshot: ConfigFeatureDecisionSnapshot;
  lang: "zh" | "en";
};

const FEATURE_LABELS: Record<string, { zh: string; en: string }> = {
  mental_model: { zh: "心智模型", en: "Mental model" },
  context_compression: { zh: "上下文压缩", en: "Context compression" },
  pet: { zh: "宠物状态", en: "Pet state" },
  semantic_memory: { zh: "语义记忆", en: "Semantic memory" },
  memory_extraction: { zh: "LLM 记忆提取", en: "LLM memory extraction" },
  memory_summary: { zh: "LLM 记忆摘要", en: "LLM memory summary" },
  supervised_evolution: { zh: "监督进化", en: "Supervised evolution" },
  supervised_mental_model: { zh: "监督心智模型", en: "Supervised mental model" },
  self_evolution: { zh: "自进化", en: "Self evolution" },
};

function reasonLabel(reason: string, lang: "zh" | "en") {
  const labels: Record<string, { zh: string; en: string }> = {
    operator_config_enabled: { zh: "操作员配置已开启", en: "Enabled by operator config" },
    operator_config_disabled: { zh: "操作员配置已关闭", en: "Disabled by operator config" },
    run_narrowed_disabled: { zh: "本轮运行已收窄关闭", en: "Disabled for this run" },
    managed_policy_denied: { zh: "托管策略已拒绝", en: "Denied by managed policy" },
  };
  return labels[reason]?.[lang] ?? reason;
}

export function ConfigFeatureDecisionPanel({
  snapshot,
  lang,
}: ConfigFeatureDecisionPanelProps) {
  const entries = Object.entries(snapshot.features);
  const enabledCount = entries.filter(([, decision]) => decision.effectiveEnabled).length;
  const title = lang === "zh" ? "可信功能决策" : "Trusted feature decisions";
  const body =
    lang === "zh"
      ? "这里展示当前配置草稿会产生的有效功能状态。请求只能关闭功能，不能绕过操作员配置开启功能。"
      : "This shows the effective feature state produced by the current draft. A request may disable a feature, but cannot enable one that operator config disabled.";

  return (
    <VSection
      id="config-feature-decisions"
      className={styles.section}
      eyebrow={title}
      title={title}
    >
      <p className={styles.body}>{body}</p>
      <VStatusStrip
        aria-label={title}
        items={[
          {
            label: lang === "zh" ? "有效开启" : "Effectively enabled",
            value: `${enabledCount}/${entries.length}`,
            tone: enabledCount ? "success" : "neutral",
          },
          {
            label: lang === "zh" ? "配置来源" : "Config source",
            value: snapshot.source,
          },
          {
            label: lang === "zh" ? "配置指纹" : "Config revision",
            value: snapshot.configRevision,
            tone: "info",
          },
        ]}
      />
      <div className={styles.grid}>
        {entries.map(([feature, decision]) => {
          const label = FEATURE_LABELS[feature]?.[lang] ?? feature;
          const enabled = decision.effectiveEnabled;
          return (
            <article
              key={feature}
              className={styles.card}
            >
              <span
                className={
                  enabled
                    ? styles.enabledIcon
                    : styles.disabledIcon
                }
              >
                {enabled ? <CheckCircle2 size={17} /> : <CircleOff size={17} />}
              </span>
              <div className={styles.cardContent}>
                <div className={styles.cardHeader}>
                  <strong className={styles.cardTitle}>{label}</strong>
                  <span className={styles.cardStatus}>
                    {enabled
                      ? lang === "zh" ? "开启" : "Enabled"
                      : lang === "zh" ? "关闭" : "Disabled"}
                  </span>
                </div>
                <p className={styles.reason}>
                  {reasonLabel(decision.featureDecisionReason, lang)}
                </p>
                <p className={styles.provenance}>
                  <Fingerprint size={12} />
                  {feature} · {decision.featureSource}
                </p>
              </div>
            </article>
          );
        })}
      </div>
    </VSection>
  );
}
