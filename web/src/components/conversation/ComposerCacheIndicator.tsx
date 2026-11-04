import { useState } from "react";
import { Database, RefreshCw, X } from "lucide-react";
import { VButton, VPopover } from "../vui";
import type { ComposerCacheUsageModel } from "./composerCacheUsageModel";
import styles from "./ComposerCacheIndicator.styles";

function CacheIndicator({ model, lang }: { model: ComposerCacheUsageModel; lang: "zh" | "en" }) {
  const [open, setOpen] = useState(false);
  const zh = lang === "zh";
  const value = (rate: number | null) => rate === null ? "—" : `${rate}%`;
  const status = model.state === "error" ? zh ? "暂时无法读取" : "Temporarily unavailable"
    : model.state === "loading" ? zh ? "读取中" : "Loading"
      : model.state === "not_called" ? zh ? "尚未调用" : "No calls yet"
        : model.state === "missing" ? zh ? "上游未提供数据" : "No provider data" : "";
  const label = `${zh ? "本会话缓存命中率" : "Session cache hit rate"} ${value(model.sessionPercent)}`;
  return <VPopover open={open} onOpenChange={setOpen} side="top" align="end" sideOffset={10}
    aria-label={zh ? "缓存命中详情" : "Cache hit details"} contentClassName={styles.popover}
    trigger={<VButton variant="ghost" contentLayout="plain" className={styles.trigger}
      aria-label={label} tooltip={open ? undefined : label} data-testid="composer-cache-indicator">
      <Database size={15} aria-hidden="true" /><span>{value(model.sessionPercent)}</span>
      {model.state === "partial" && <span className={styles.partial}>{zh ? "部分" : "Partial"}</span>}
      {model.updating && <RefreshCw size={12} aria-label={zh ? "统计中" : "Updating"} />}
    </VButton>}>
    <header className={styles.header}><strong>{zh ? "缓存命中率" : "Cache hit rate"}</strong>
      <VButton variant="ghost" isIconOnly className={styles.close}
        aria-label={zh ? "关闭缓存详情" : "Close cache details"} onPress={() => setOpen(false)}><X size={15} /></VButton>
    </header>
    {model.sessionPercent !== null || model.lastCallPercent !== null ? <dl className={styles.rows}>
      <div><dt>{zh ? "本会话" : "Session"}</dt><dd>{value(model.sessionPercent)}</dd></div>
      <div><dt>{zh ? "最近一次" : "Last call"}</dt><dd>{value(model.lastCallPercent)}</dd></div>
    </dl> : null}
    {status ? <p className={styles.status}>{status}</p> : null}
    {model.state === "partial" ? <p className={styles.status}>
      {model.observedCalls}/{model.totalCalls} {zh ? "次调用已上报" : "calls reported"}
    </p> : null}
    {model.updating && !status ? <p className={styles.status}>{zh ? "本轮统计中" : "Updating this turn"}</p> : null}
  </VPopover>;
}

export function ComposerCacheIndicator({ sessionId, ...props }: {
  sessionId: string;
  model: ComposerCacheUsageModel;
  lang: "zh" | "en";
}) {
  return <CacheIndicator key={sessionId} {...props} />;
}
