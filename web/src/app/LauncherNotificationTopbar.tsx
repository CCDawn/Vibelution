import { Bell, ChevronDown, ImageOff, Info, TriangleAlert, WifiOff, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { VButton, VChip, VErrorSummary, VIconButton, VPopover } from "../components/vui";
import { useLauncherNotices, type LauncherNotice, type LauncherNoticeAction } from "./LauncherNotifications";
import styles from "./LauncherNotificationTopbar.styles";

function noticeIcon(notice: LauncherNotice) {
  const Icon = notice.kind === "connection" ? WifiOff : notice.kind === "appearance" ? ImageOff
    : notice.tone === "warning" ? TriangleAlert : Info;
  return <Icon size={16} aria-hidden="true" />;
}

export function LauncherNotificationTopbar({ lang }: { lang: "zh" | "en" }) {
  const zh = lang === "zh";
  const notices = useLauncherNotices();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const focusedRetry = useRef<HTMLButtonElement | null>(null);
  // This lock survives closing the popover and blocks clicks before React commits.
  const actionLocks = useRef(new Set<string>());
  const [pendingActions, setPendingActions] = useState(new Set<string>());
  useEffect(() => {
    const button = focusedRetry.current;
    if (!button || button.isConnected && !button.disabled) return;
    if (document.activeElement === document.body || document.activeElement === button) triggerRef.current?.focus();
    focusedRetry.current = null;
  }, [notices, pendingActions]);
  const ordered = [...notices].sort((a, b) => Number(b.tone === "warning") - Number(a.tone === "warning"));
  const warning = ordered.some(notice => notice.tone === "warning");
  const connection = ordered.some(notice => notice.kind === "connection" && notice.tone === "warning");
  const heading = zh ? "运行提醒" : "Runtime notices";
  const label = connection ? (zh ? "连接异常" : "Connection issue")
    : warning ? (zh ? "有异常" : "Attention needed")
      : notices.length ? heading : (zh ? "暂无异常" : "No issues reported");
  const countLabel = zh ? `${notices.length} 项提醒` : `${notices.length} ${notices.length === 1 ? "notice" : "notices"}`;
  const actionKey = (notice: LauncherNotice, action: LauncherNoticeAction) => JSON.stringify([notice.id, action.id]);

  async function runAction(notice: LauncherNotice, action: LauncherNoticeAction, button: HTMLButtonElement) {
    const key = actionKey(notice, action);
    if (action.pending || action.disabled || actionLocks.current.has(key)) return;
    if (document.activeElement === button) focusedRetry.current = button;
    actionLocks.current.add(key);
    setPendingActions(new Set(actionLocks.current));
    try {
      await action.run();
    } catch {
      // The producer owns the failure and removes the notice only after recovery.
    } finally {
      actionLocks.current.delete(key);
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
        {notices.length ? <VChip tone={warning ? "warning" : "neutral"} className={styles.count} aria-hidden="true">{notices.length}</VChip> : null}
      </VButton>}>
      <div className={styles.header}>
        <h2 className={styles.heading}>{heading}<span className={styles.metadata}>{zh ? `${notices.length} 项` : countLabel}</span></h2>
        <VIconButton label={zh ? "关闭运行提醒" : "Close runtime notices"} variant="ghost" className={styles.close}
          icon={<X size={15} aria-hidden="true" />} onPress={() => setOpen(false)} />
      </div>
      {ordered.length ? <ul className={styles.list} aria-label={heading}>
        {ordered.map(notice => <li key={notice.id} className={styles.item}>
          <VErrorSummary className={styles.notice} tone={notice.tone} icon={noticeIcon(notice)}
            summary={<span className={styles.copy}>
              <span className={styles.title}>{notice.title}</span>
              <span className={styles.description}>{notice.description}</span>
              {notice.labels?.length ? <span className={styles.labels}>
                {notice.labels.map((label, index) => <VChip key={`${index}:${label}`} tone="neutral" className={styles.label}>{label}</VChip>)}
              </span> : null}
            </span>}
            details={notice.details ? <code className={styles.details}>{notice.details}</code> : undefined}
            openLabel={zh ? "技术详情" : "Technical details"} closeLabel={zh ? "收起详情" : "Hide details"}
            actions={notice.actions?.length ? notice.actions.map(action => <VButton key={action.id} variant="secondary"
              density="compact" className={styles.action} isDisabled={action.disabled}
              isPending={action.pending || pendingActions.has(actionKey(notice, action))}
              onPress={event => { void runAction(notice, action, event.currentTarget); }}>{action.label}</VButton>) : undefined} />
        </li>)}
      </ul> : <div className={styles.empty} role="status">
        <Bell size={22} className={styles.emptyIcon} aria-hidden="true" />
        <span>{zh ? "当前没有异常" : "No current issues"}</span>
      </div>}
      <div className={styles.footer}>{zh ? "恢复后自动移除提醒" : "Notices clear automatically after recovery"}</div>
    </VPopover>
  </div>;
}
