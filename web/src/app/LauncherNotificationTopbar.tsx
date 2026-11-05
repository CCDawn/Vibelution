import { Bell, ChevronDown, Clock3, ImageOff, Info, TriangleAlert, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { VButton, VErrorSummary, VIconButton, VPopover } from "../components/vui";
import { useLauncherNotices, type LauncherNotice, type LauncherNoticeAction, type LauncherNoticeFeature } from "./LauncherNotifications";
import styles from "./LauncherNotificationTopbar.styles";

type NoticeAction = { notice: LauncherNotice; action: LauncherNoticeAction };
type NoticeGroup = { id: string; sources: LauncherNotice[]; features: LauncherNoticeFeature[] };

const FEATURE_COPY: Record<LauncherNoticeFeature, [string, string, string, string]> = {
  conversation: ["聊天记录", "Chat messages", "没能刷新", "Could not refresh"],
  approvals: ["待你确认的操作", "Actions awaiting your approval", "暂时查不到", "Temporarily unavailable"],
  tasks: ["任务进度", "Task progress", "暂时查不到", "Temporarily unavailable"],
  assistant: ["助理信息", "Assistant information", "暂时查不到", "Temporarily unavailable"],
};

function groupNotices(notices: LauncherNotice[]): NoticeGroup[] {
  const groups: NoticeGroup[] = [];
  for (const notice of [...notices].sort((a, b) => Number(b.tone === "warning") - Number(a.tone === "warning"))) {
    // Combine the affected reads for presentation, without asserting a common cause.
    const grouped = notice.kind === "connection" && notice.tone === "warning" && Boolean(notice.features?.length);
    const id = grouped ? "assistant-read-status" : notice.id;
    let group = groups.find(candidate => candidate.id === id);
    if (!group) { group = { id, sources: [], features: [] }; groups.push(group); }
    group.sources.push(notice);
    for (const feature of notice.features ?? []) if (!group.features.includes(feature)) group.features.push(feature);
  }
  return groups;
}

function groupTitle(group: NoticeGroup, zh: boolean): string {
  const { features } = group;
  if (features.includes("tasks")) {
    if (features.includes("conversation")) return zh ? "聊天和任务进度没刷新" : "Chat and task progress could not refresh";
    if (features.includes("approvals")) return zh ? "待确认操作和任务进度没刷新" : "Approvals and task progress could not refresh";
    return zh ? "暂时查不到任务进度" : "Task progress is unavailable";
  }
  if (features.includes("conversation")) return zh ? "聊天没能刷新" : "Chat could not refresh";
  if (features.includes("approvals")) return zh ? "暂时查不到待确认的操作" : "Pending approvals are unavailable";
  if (features.includes("assistant")) return zh ? "暂时查不到助理信息" : "Assistant information is unavailable";
  return group.sources[0].title;
}

function noticeIcon(notice: LauncherNotice) {
  const Icon = notice.kind === "connection" ? Clock3 : notice.kind === "appearance" ? ImageOff
    : notice.tone === "warning" ? TriangleAlert : Info;
  return <Icon size={16} className={notice.tone === "warning" ? styles.iconWarning : styles.iconQuiet} aria-hidden="true" />;
}

export function LauncherNotificationTopbar({ lang }: { lang: "zh" | "en" }) {
  const zh = lang === "zh";
  const notices = useLauncherNotices();
  const groups = groupNotices(notices);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(new Set<string>());
  const detailsId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const focusedRetry = useRef<HTMLButtonElement | null>(null);
  const actionLocks = useRef(new Set<string>());
  const [pendingActions, setPendingActions] = useState(new Set<string>());
  useEffect(() => {
    const button = focusedRetry.current;
    if (!button || button.isConnected && !button.disabled) return;
    if (document.activeElement === document.body || document.activeElement === button) triggerRef.current?.focus();
    focusedRetry.current = null;
  }, [notices, pendingActions]);
  const warning = notices.some(notice => notice.tone === "warning");
  const connection = notices.some(notice => notice.kind === "connection" && notice.tone === "warning");
  const heading = zh ? "运行提醒" : "Runtime notices";
  const label = connection ? (zh ? "刷新没成功" : "Refresh failed")
    : warning ? (zh ? "有异常" : "Attention needed")
      : notices.length ? heading : (zh ? "暂无异常" : "No issues reported");
  const countLabel = zh ? `${groups.length} 项提醒` : `${groups.length} ${groups.length === 1 ? "notice" : "notices"}`;
  const actionKey = ({ notice, action }: NoticeAction) => JSON.stringify([notice.id, action.id]);

  async function runActions(actions: NoticeAction[], button: HTMLButtonElement) {
    if (actions.some(item => item.action.pending || item.action.disabled || actionLocks.current.has(actionKey(item)))) return;
    if (document.activeElement === button) focusedRetry.current = button;
    const keys = actions.map(actionKey);
    keys.forEach(key => actionLocks.current.add(key));
    setPendingActions(new Set(actionLocks.current));
    try {
      // Keep every read locked until all settle, even if a sibling rejects early.
      await Promise.allSettled(actions.map(({ action }) => Promise.resolve().then(() => action.run())));
    } finally {
      keys.forEach(key => actionLocks.current.delete(key));
      setPendingActions(new Set(actionLocks.current));
    }
  }

  return <div className={styles.root}>
    <VPopover open={open} onOpenChange={setOpen} side="bottom" align="end" aria-label={heading}
      contentClassName={styles.panel}
      trigger={<VButton ref={triggerRef} variant="ghost" density="compact" contentLayout="plain"
        className={[styles.trigger, warning ? styles.triggerWarning : styles.triggerQuiet].join(" ")}
        aria-label={`${label}, ${countLabel}, ${zh ? "查看详情" : "View details"}`}
        icon={warning ? <TriangleAlert size={15} aria-hidden="true" /> : <Bell size={15} aria-hidden="true" />}
        trailingIcon={<ChevronDown size={12} aria-hidden="true" />}>
        <span className={styles.triggerLabel}>{label}</span>
      </VButton>}>
      {groups.length ? <ul className={styles.list} aria-label={heading}>
        {groups.map((group, index) => {
          const source = group.sources[0];
          const actions = group.sources.flatMap(notice => notice.actions?.map(action => ({ notice, action })) ?? []);
          const pending = actions.some(item => item.action.pending || pendingActions.has(actionKey(item)));
          const reading = Boolean(group.features.length);
          const title = pending && reading ? (zh ? "正在刷新…" : "Refreshing…") : groupTitle(group, zh);
          const shown = expanded.has(group.id);
          const contentId = `${detailsId}-${index}`;
          const diagnostic = group.sources.map(notice => notice.details).filter(Boolean).join("\n").slice(0, 2_000);
          const actionSets = reading ? [actions] : actions.map(action => [action]);
          return <li key={group.id} className={styles.item} data-tone={source.tone}>
            <div className={styles.row}>
              <VButton variant="ghost" density="compact" contentLayout="plain" className={styles.summary}
                aria-expanded={shown} aria-controls={contentId} icon={noticeIcon(source)}
                trailingIcon={<ChevronDown size={12} className={shown ? "rotate-180" : undefined} aria-hidden="true" />}
                onPress={() => setExpanded(previous => {
                  const next = new Set(previous); if (next.has(group.id)) next.delete(group.id); else next.add(group.id); return next;
                })}>
                <span className={styles.title} role="status" aria-live="polite">{title}</span>
              </VButton>
              <div className={styles.actions}>
                {actions.length ? actionSets.map(items => <VButton key={actionKey(items[0])} variant="secondary" density="compact"
                  className={styles.action} isDisabled={items.some(item => item.action.disabled)}
                  isPending={items.some(item => item.action.pending || pendingActions.has(actionKey(item)))}
                  onPress={event => { void runActions(items, event.currentTarget); }}>
                  {reading ? (pending ? (zh ? "请稍等" : "Please wait") : (zh ? "再试一次" : "Try again")) : items[0].action.label}
                </VButton>) : null}
              </div>
              {index === 0 ? <VIconButton label={zh ? "关闭运行提醒" : "Close runtime notices"} variant="ghost" className={styles.close}
                icon={<X size={14} aria-hidden="true" />} onPress={() => setOpen(false)} /> : null}
            </div>
            <div className={styles.content} id={contentId} hidden={!shown}>
              {shown ? <>
              {reading ? <dl className={styles.features}>
                {group.features.map(feature => <div className={styles.feature} key={feature}>
                  <dt>{FEATURE_COPY[feature][zh ? 0 : 1]}</dt>
                  <dd>{pending ? (zh ? "正在刷新…" : "Refreshing…") : FEATURE_COPY[feature][zh ? 2 : 3]}</dd>
                </div>)}
              </dl> : group.sources.map(notice => <div key={notice.id} className={styles.description}>
                <p>{notice.description}</p>
                {notice.labels?.length ? <p>{notice.labels.join(zh ? "、" : ", ")}</p> : null}
              </div>)}
              {diagnostic ? <VErrorSummary className={styles.diagnostic} tone="info" summary={zh ? "错误详情" : "Error details"}
                details={<code className={styles.details}>{diagnostic}</code>}
                openLabel={zh ? "展开" : "Show"} closeLabel={zh ? "收起" : "Hide"} /> : null}
              </> : null}
            </div>
          </li>;
        })}
      </ul> : <div className={styles.empty} role="status">
        <span>{zh ? "当前没有异常" : "No current issues"}</span>
        <VIconButton label={zh ? "关闭运行提醒" : "Close runtime notices"} variant="ghost" className={styles.close}
          icon={<X size={14} aria-hidden="true" />} onPress={() => setOpen(false)} />
      </div>}
    </VPopover>
  </div>;
}
