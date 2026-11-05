import { ChevronRight, Gauge, X } from "lucide-react";
import { useState } from "react";

import type { ComposerContextRingModel } from "../../routes/chat/composerContextModel";
import { VButton, VPopover } from "../vui";
import { ComposerContextRingPanel } from "./ComposerContextRing";
import type { ComposerCacheUsageModel } from "./composerCacheUsageModel";
import styles from "./ConversationComposerMetrics.styles";

type ConversationComposerMetricsProps = {
  sessionId: string;
  lang: "zh" | "en";
  contextModel?: ComposerContextRingModel | null;
  cacheUsage?: ComposerCacheUsageModel | null;
  onOpenContextDetail?: () => void;
};

function hasUsageData({ contextModel, cacheUsage }: ConversationComposerMetricsProps) {
  return Boolean(
    contextModel && (!contextModel.empty || contextModel.groups.length > 0
      || contextModel.cacheState === "observed" || contextModel.generationTokensPerSecond !== null)
    || cacheUsage && (cacheUsage.sessionPercent !== null || cacheUsage.lastCallPercent !== null
      || cacheUsage.totalCalls > 0 || cacheUsage.updating
      || cacheUsage.state === "loading" || cacheUsage.state === "error"),
  );
}

function SessionComposerMetrics({
  lang, contextModel, cacheUsage, onOpenContextDetail,
}: ConversationComposerMetricsProps) {
  const [open, setOpen] = useState(false);
  const zh = lang === "zh";
  const label = zh ? "上下文与缓存用量" : "Context and cache usage";
  const cacheValue = (value: number | null) => value === null ? "—" : `${value}%`;
  const cacheStatus = cacheUsage?.state === "error" ? (zh ? "暂时无法读取" : "Temporarily unavailable")
    : cacheUsage?.state === "loading" ? (zh ? "读取中" : "Loading")
      : cacheUsage?.state === "not_called" ? (zh ? "尚未调用" : "No calls yet")
        : cacheUsage?.state === "missing" ? (zh ? "上游未提供数据" : "No provider data") : "";
  const openContextDetail = onOpenContextDetail ? () => {
    setOpen(false);
    onOpenContextDetail();
  } : undefined;

  return (
    <div className={styles.root} data-testid="conversation-composer-metrics">
      <VPopover
        open={open}
        onOpenChange={setOpen}
        side="top"
        align="end"
        sideOffset={10}
        aria-label={label}
        contentClassName={styles.popover}
        trigger={(
          <VButton
            variant="ghost"
            isIconOnly
            className={styles.trigger}
            aria-label={label}
            title={label}
            data-testid="conversation-composer-metrics-trigger"
          >
            <Gauge size={15} aria-hidden="true" />
          </VButton>
        )}
      >
        {contextModel ? (
          <ComposerContextRingPanel
            model={contextModel}
            lang={lang}
            onClose={() => setOpen(false)}
            onOpenDetail={openContextDetail}
          />
        ) : (
          <header className={styles.header}>
            <strong>{zh ? "用量详情" : "Usage details"}</strong>
            <VButton
              variant="ghost"
              isIconOnly
              className={styles.close}
              aria-label={zh ? "关闭用量详情" : "Close usage details"}
              onPress={() => setOpen(false)}
            >
              <X size={14} aria-hidden="true" />
            </VButton>
          </header>
        )}
        {cacheUsage ? (
          <section className={contextModel ? styles.cacheSection : undefined}
            data-composer-session-cache="true" data-cache-state={cacheUsage.state}>
            <h2 className={styles.cacheTitle}>{zh ? "缓存命中率" : "Cache hit rate"}</h2>
            {cacheUsage.sessionPercent !== null || cacheUsage.lastCallPercent !== null ? (
              <dl className={styles.rows}>
                <div><dt>{zh ? "本会话" : "Session"}</dt><dd>{cacheValue(cacheUsage.sessionPercent)}</dd></div>
                <div><dt>{zh ? "最近一次" : "Last call"}</dt><dd>{cacheValue(cacheUsage.lastCallPercent)}</dd></div>
              </dl>
            ) : null}
            {cacheStatus ? <p className={styles.note}>{cacheStatus}</p> : null}
            {cacheUsage.state === "partial" ? (
              <p className={styles.note}>{cacheUsage.observedCalls}/{cacheUsage.totalCalls} {zh ? "次调用已上报" : "calls reported"}</p>
            ) : null}
            {cacheUsage.updating ? <p className={styles.note}>{zh ? "本轮统计中" : "Updating this turn"}</p> : null}
          </section>
        ) : null}
        {contextModel?.detailAvailable && contextModel.groups.length === 0 && openContextDetail ? (
          <VButton variant="ghost" contentLayout="plain" className={styles.detailLink} onPress={openContextDetail}>
            <span>{zh ? "查看缓存诊断" : "View cache diagnostics"}</span>
            <ChevronRight size={14} aria-hidden="true" />
          </VButton>
        ) : null}
      </VPopover>
    </div>
  );
}

/** Hosts supply observed models; this shared control performs no Session requests. */
export function ConversationComposerMetrics(props: ConversationComposerMetricsProps) {
  if (!hasUsageData(props)) return null;
  return <SessionComposerMetrics key={props.sessionId} {...props} />;
}
