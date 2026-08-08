import { ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { VButton, VTooltip } from "../../components/vui";
import routeStyles from "../ChatCodingRoute.styles";
import styles from "./ChatStatusRail.styles";
import {
  TURN_STATUS_TAIL_BLOCK_META,
  defaultTurnStatusTailConfig,
  estimateTurnStatusTailRisk,
  loadTurnStatusTailConfig,
  normalizeTurnStatusTailConfig,
  saveTurnStatusTailConfig,
  type TurnStatusTailBlockId,
  type TurnStatusTailConfig,
} from "./turnStatusTailModel";

export type TurnStatusTailPanelProps = {
  activeSessionId: string;
  lang: "zh" | "en";
  injectMasterEnabled: boolean;
  /**
   * `section` — standalone left-rail card (legacy).
   * `embedded` — body-only under 心智与运行, default-collapsed details.
   */
  variant?: "section" | "embedded";
};

export function TurnStatusTailPanel({
  activeSessionId,
  lang,
  injectMasterEnabled,
  variant = "section",
}: TurnStatusTailPanelProps) {
  const [config, setConfig] = useState<TurnStatusTailConfig>(() =>
    activeSessionId ? loadTurnStatusTailConfig(activeSessionId) : defaultTurnStatusTailConfig(),
  );

  useEffect(() => {
    if (!activeSessionId) {
      setConfig(defaultTurnStatusTailConfig());
      return;
    }
    setConfig(loadTurnStatusTailConfig(activeSessionId));
  }, [activeSessionId]);

  const risk = useMemo(() => estimateTurnStatusTailRisk(config, lang), [config, lang]);
  const disabled = !activeSessionId || !injectMasterEnabled;

  const persist = (next: TurnStatusTailConfig) => {
    const normalized = normalizeTurnStatusTailConfig(next);
    setConfig(normalized);
    if (activeSessionId) {
      saveTurnStatusTailConfig(activeSessionId, normalized);
    }
  };

  const toggleBlock = (id: TurnStatusTailBlockId) => {
    if (disabled) return;
    persist({
      ...config,
      blocks: {
        ...config.blocks,
        [id]: !config.blocks[id],
      },
    });
  };

  const toggleEnabled = () => {
    if (!activeSessionId) return;
    persist({ ...config, enabled: !config.enabled });
  };

  const body = (
    <>
      <p className={styles.groupManagementHint}>
        {lang === "zh"
          ? "默认仅预算与时钟；Git/路径默认关。全文 diff 不提供。"
          : "Defaults: budget + clock. Full diff is not offered."}
      </p>
      {!injectMasterEnabled ? (
        <p className={styles.groupManagementHint}>
          {lang === "zh"
            ? "总闸「状态」已关：下方勾选不会注入模型。"
            : "Master Status toggle is off: blocks below will not inject."}
        </p>
      ) : null}
      <div className={styles.featureChipRow}>
        <VButton
          type="button"
          contentLayout="plain"
          className={
            config.enabled && injectMasterEnabled
              ? `${styles.featureChip} ${styles.featureChipPrimary} ${styles.featureChipPrimaryActive}`
              : `${styles.featureChip} ${styles.featureChipPrimary}`
          }
          aria-pressed={config.enabled}
          isDisabled={!activeSessionId}
          onClick={toggleEnabled}
          title={lang === "zh" ? "本会话是否允许尾部拼装" : "Allow tail composition for this session"}
        >
          <strong>{lang === "zh" ? "尾部拼装" : "Tail compose"}</strong>
          <em>{config.enabled ? (lang === "zh" ? "开" : "On") : (lang === "zh" ? "关" : "Off")}</em>
        </VButton>
        {TURN_STATUS_TAIL_BLOCK_META.map((item) => {
          const on = Boolean(config.blocks[item.id]);
          return (
            <VTooltip
              key={item.id}
              content={lang === "zh" ? item.hintZh : item.hintEn}
              width="wide"
            >
              <span>
                <VButton
                  type="button"
                  contentLayout="plain"
                  className={
                    on && !disabled
                      ? `${styles.featureChip} ${styles.featureChipActive}`
                      : styles.featureChip
                  }
                  aria-pressed={on}
                  isDisabled={disabled || !config.enabled}
                  onClick={() => toggleBlock(item.id)}
                >
                  <strong>{lang === "zh" ? item.zh : item.en}</strong>
                  <em>{on ? (lang === "zh" ? "开" : "On") : (lang === "zh" ? "关" : "Off")}</em>
                </VButton>
              </span>
            </VTooltip>
          );
        })}
      </div>
      <div className={styles.activeSkillMeta}>
        <span>
          {lang === "zh" ? "风险" : "Risk"}: {risk.label}
        </span>
        <span>
          max {config.limits.maxTailChars} {lang === "zh" ? "字" : "chars"}
        </span>
      </div>
    </>
  );

  if (variant === "embedded") {
    return (
      <details
        className={styles.compactDetails}
        data-testid="turn-status-tail-panel"
        aria-label={lang === "zh" ? "回合尾部现场" : "Turn tail context"}
      >
        <summary>
          <ChevronRight size={14} aria-hidden="true" />
          <span className={styles.compactDetailsClosedLabel}>
            {lang === "zh" ? "尾部现场" : "Tail context"}
            {!injectMasterEnabled
              ? (lang === "zh" ? " · 状态关" : " · status off")
              : config.enabled
                ? (lang === "zh" ? " · 开" : " · on")
                : (lang === "zh" ? " · 关" : " · off")}
          </span>
          <span className={styles.compactDetailsOpenLabel}>
            {lang === "zh" ? "收起尾部" : "Collapse tail"}
          </span>
        </summary>
        <div className={styles.embeddedTailBody}>{body}</div>
      </details>
    );
  }

  return (
    <section
      className={`${routeStyles.leftBlock} ${styles.featurePresetBlock}`}
      data-testid="turn-status-tail-panel"
      aria-label={lang === "zh" ? "回合尾部现场" : "Turn tail context"}
    >
      <div className={routeStyles.sectionHeader}>
        <h3 className={routeStyles.railSectionHeading}>
          {lang === "zh" ? "回合尾部现场" : "Turn tail context"}
        </h3>
        <span
          className={styles.featurePresetScope}
          title={
            lang === "zh"
              ? "会话级：勾选后在模型消息列表尾部追加；不影响前缀缓存形态"
              : "Session-level: append selected blocks at message-list tail (prefix-cache safe)"
          }
        >
          {lang === "zh" ? "会话 · 尾部" : "Session · tail"}
        </span>
      </div>
      {body}
    </section>
  );
}
