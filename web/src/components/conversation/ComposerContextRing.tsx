import { useState } from "react";
import { ArrowLeft, ChevronDown, ChevronRight, X } from "lucide-react";
import { VButton, VPopover } from "../vui";
import type { ComposerContextRingModel } from "../../routes/chat/composerContextModel";
import styles from "./ComposerContextRing.styles";

export type ComposerContextRingProps = {
  model: ComposerContextRingModel;
  lang: "zh" | "en";
  sessionId?: string | null;
  onOpenDetail?: () => void;
};
export type ComposerContextRingPanelProps = Omit<
  ComposerContextRingProps,
  "sessionId"
> & { onClose?: () => void };

export function ComposerContextRingPanel({
  model,
  lang,
  onOpenDetail,
  onClose,
}: ComposerContextRingPanelProps) {
  const [detail, setDetail] = useState(false);
  const [expanded, setExpanded] = useState("");
  const zh = lang === "zh";
  const cacheLabel =
    model.cacheState === "observed"
      ? zh
        ? `已复用 ${model.hitPercent}% 输入`
        : `${model.hitPercent}% of input reused`
      : model.cacheState === "not_called"
        ? zh
          ? "尚未调用模型"
          : "Model not called yet"
        : zh
          ? "暂无上游数据"
          : "Not reported by provider";
  const note = model.empty
    ? zh
      ? "模型调用后显示用量。"
      : "Usage appears after a model call."
    : !model.capacityKnown
      ? zh
        ? "窗口上限未知，暂不计算占比。"
        : "Window limit unknown; percentage unavailable."
      : model.usagePercent >= 90
        ? zh
          ? "接近窗口上限，可查看主要占用来源。"
          : "Near the window limit. Review the main sources."
        : zh
          ? `窗口余量约 ${model.remainingLabel} · 最近一次上下文估算`
          : `About ${model.remainingLabel} of window remaining · Latest context estimate`;
  return (
    <>
      <div className={styles.head}>
        {detail ? (
          <VButton
            variant="ghost"
            contentLayout="plain"
            className={styles.back}
            onClick={() => {
              setDetail(false);
              setExpanded("");
            }}
          >
            <ArrowLeft size={14} />
            {zh ? "上下文明细" : "Context details"}
          </VButton>
        ) : (
          <strong className={styles.title}>{zh ? "上下文" : "Context"}</strong>
        )}
        {onClose && (
          <VButton
            variant="ghost"
            isIconOnly
            className={styles.close}
            aria-label={zh ? "关闭上下文卡片" : "Close context"}
            onClick={onClose}
          >
            <X size={14} />
          </VButton>
        )}
      </div>
      <div className={styles.capacity}>
        <span>
          {model.empty ? (
            zh ? (
              "暂无用量数据"
            ) : (
              "No usage data"
            )
          ) : (
            <>
              {zh ? "已用" : "Used"} <b>{model.usageLabel}</b>
            </>
          )}
        </span>
        <span className={styles.nums}>
          {model.empty ? "— / —" : model.usedLabel} <span>tokens</span>
        </span>
      </div>
      <div
        className={styles.track}
        role="progressbar"
        aria-label={zh ? "上下文容量占用" : "Context window usage"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={model.capacityKnown ? model.usagePercent : undefined}
        aria-valuetext={
          model.capacityKnown ? model.usageLabel : zh ? "未知" : "Unknown"
        }
      >
        <i
          className={
            model.usagePercent >= 90 ? styles.warningFill : styles.fill
          }
          style={{ width: `${model.usagePercent}%` }}
        />
      </div>
      <p className={styles.note}>{note}</p>
      {model.groups.length > 0 && (
        <section data-composer-context-composition="true">
          <h2 className={styles.sectionTitle}>
            <span>
              {detail
                ? zh
                  ? "按来源查看"
                  : "By source"
                : zh
                  ? "主要占用"
                  : "Main sources"}
            </span>
            <span>tokens</span>
          </h2>
          {model.groups.map((group) => (
            <div key={group.key}>
              {detail ? (
                <>
                  <VButton
                    variant="ghost"
                    contentLayout="plain"
                    className={styles.detailRow}
                    aria-expanded={expanded === group.key}
                    onClick={() =>
                      setExpanded(expanded === group.key ? "" : group.key)
                    }
                  >
                    <ChevronDown
                      size={13}
                      className={expanded === group.key ? "" : "-rotate-90"}
                    />
                    <span className={styles.name}>{group.name}</span>
                    <b>{group.tokensLabel}</b>
                  </VButton>
                  {expanded === group.key && (
                    <div className={styles.expanded}>
                      {group.segments.map((segment) => (
                        <div key={segment.key} data-context-row={segment.key}>
                          <div className={styles.segment}>
                            <span className={styles.name}>{segment.name}</span>
                            <span className={styles.muted}>
                              {segment.pctLabel}
                            </span>
                            <span>{segment.tokensLabel}</span>
                          </div>
                          {segment.contentPreview && (
                            <p
                              className={styles.preview}
                              data-context-preview={segment.key}
                            >
                              {segment.contentPreview}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className={styles.row}>
                  <span className={styles.name}>{group.name}</span>
                  <b>{group.tokensLabel}</b>
                </div>
              )}
            </div>
          ))}
        </section>
      )}
      <div
        className={styles.cache}
        data-composer-context-cache="true"
        data-cache-state={model.cacheState}
      >
        <span>{zh ? "上次调用缓存" : "Last call cache"}</span>
        <span
          className={
            model.cacheState === "observed" ? styles.observed : styles.muted
          }
        >
          {cacheLabel}
        </span>
      </div>
      {detail && (
        <p className={styles.detailNote}>
          {zh
            ? "分段为独立估算，可能与总量略有差异；比例以列出内容为基准。缓存影响费用与速度，不减少上下文占用。"
            : "Segments are independently estimated and may differ slightly from the total; shares refer to listed content. Caching affects cost and speed, not context size."}
        </p>
      )}
      {!detail && model.groups.length > 0 && (
        <VButton
          variant="ghost"
          contentLayout="plain"
          className={styles.detailLink}
          onClick={() => setDetail(true)}
        >
          <span>{zh ? "查看完整明细" : "View breakdown"}</span>
          <ChevronRight size={14} />
        </VButton>
      )}
      {detail && onOpenDetail && model.detailAvailable && (
        <VButton
          variant="ghost"
          contentLayout="plain"
          className={styles.detailLink}
          onClick={onOpenDetail}
        >
          <span>{zh ? "查看缓存诊断" : "View cache diagnostics"}</span>
          <ChevronRight size={14} />
        </VButton>
      )}
    </>
  );
}

function SessionContextRing({
  model,
  lang,
  sessionId,
  onOpenDetail,
}: ComposerContextRingProps) {
  const [open, setOpen] = useState(false);
  const ringTitle = model.empty
    ? lang === "zh"
      ? "暂无上下文数据"
      : "No context data yet"
    : `${lang === "zh" ? "上下文占用" : "Context usage"} ${model.usageLabel} · ${model.usedLabel}`;
  return (
    <div className={styles.root} data-testid="composer-context-ring">
      <VPopover
        open={open}
        onOpenChange={setOpen}
        side="top"
        align="end"
        sideOffset={12}
        aria-label={lang === "zh" ? "上下文用量" : "Context usage"}
        contentClassName={styles.popover}
        trigger={
          <VButton
            variant="ghost"
            contentLayout="plain"
            className={styles.trigger}
            aria-label={ringTitle}
            title={ringTitle}
            data-session={sessionId || undefined}
            data-empty={model.empty ? "true" : "false"}
          >
            <svg className={styles.ring} viewBox="0 0 24 24" aria-hidden="true">
              <circle
                cx="12"
                cy="12"
                r="9"
                fill="none"
                stroke="currentColor"
                opacity=".15"
                strokeWidth="2"
              />
              <circle
                cx="12"
                cy="12"
                r="9"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                pathLength="100"
                strokeDasharray={`${model.usagePercent} 100`}
                transform="rotate(-90 12 12)"
              />
            </svg>
            <span>{model.empty ? "—" : model.usageLabel}</span>
          </VButton>
        }
      >
        <ComposerContextRingPanel
          model={model}
          lang={lang}
          onClose={() => setOpen(false)}
          onOpenDetail={
            onOpenDetail
              ? () => {
                  setOpen(false);
                  onOpenDetail();
                }
              : undefined
          }
        />
      </VPopover>
    </div>
  );
}

export function ComposerContextRing(props: ComposerContextRingProps) {
  return <SessionContextRing key={props.sessionId ?? ""} {...props} />;
}
