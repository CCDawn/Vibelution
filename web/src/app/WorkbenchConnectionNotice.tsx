import { useEffect, useState } from "react";
import { Bell, ChevronDown } from "lucide-react";

import { VButton, VPopover } from "../components/vui";
import styles from "./WorkbenchConnectionNotice.styles";

type Props = {
  unavailable: boolean;
  lang: string;
  desktopShell: boolean;
  recovering: boolean;
  lastHealthyAt?: number;
  failedAt?: number;
  onRecover: () => void;
  onRetry: () => void;
};

/** Health failure is a connection observation, not proof that the service stopped. */
export function connectionFailureIsPersistent(lastHealthyAt: number, failedAt: number): boolean {
  return lastHealthyAt === 0 || failedAt - lastHealthyAt >= 15_000;
}

/**
 * Connection health lives in the top bar next to the Tasks slot, not as a
 * full-width band over the content: a failed health check is a status, not a
 * page. It expands on its own once so the cause and the two actions are visible
 * without hunting for the trigger, and it collapses back when health returns.
 */
export function WorkbenchConnectionNotice({ unavailable, lang, desktopShell, recovering, lastHealthyAt = 0, failedAt = 0, onRecover, onRetry }: Props) {
  const zh = lang !== "en";
  const persistent = connectionFailureIsPersistent(lastHealthyAt, failedAt);
  const title = persistent
    ? (zh ? "工作台服务未连接" : "Workbench service disconnected")
    : (zh ? "连接检查暂未成功" : "Connection check failed");
  const [open, setOpen] = useState(false);

  // Proactive expand: open when health breaks, close when it recovers. A panel
  // the user closed stays closed until the next episode.
  useEffect(() => {
    setOpen(Boolean(unavailable));
  }, [unavailable]);

  if (!unavailable) return null;

  return (
    <VPopover
      open={open}
      onOpenChange={setOpen}
      align="end"
      side="bottom"
      sideOffset={8}
      aria-label={title}
      contentClassName={styles.panel}
      trigger={(
        <VButton
          type="button"
          variant="ghost"
          contentLayout="plain"
          className={styles.trigger}
          aria-expanded={open}
          aria-label={title}
          title={title}
          data-testid="workbench-connection-notice"
        >
          <span className={styles.triggerContent}>
            <Bell size={16} aria-hidden="true" />
            <ChevronDown size={13} aria-hidden="true" />
          </span>
        </VButton>
      )}
    >
      <section className={styles.panelBody} role="status" aria-live="polite" aria-label={title}>
        <strong className={styles.panelTitle}>{title}</strong>
        <span className={styles.paragraph}>{persistent
          ? (zh ? "当前内容暂不可更新，已打开的内容和草稿仍保留。" : "Content cannot update right now. Open content and drafts are retained.")
          : (zh ? "暂未确认服务状态，页面和草稿保持原样。请先检查连接。" : "Service status is unconfirmed. The page and drafts remain intact. Check the connection first.")}</span>
        {persistent ? <span className={styles.paragraph}>{desktopShell
          ? (zh ? "恢复将通过启动管理重启服务；如有运行中的任务，会先停止任务并保存已有记录。" : "Recovery restarts the service through the Launcher, stopping active tasks and saving existing records first.")
          : (zh ? "请从 Vibelution 启动管理恢复工作台，再检查连接。" : "Recover the workbench from Vibelution Launcher, then check the connection.")}</span> : null}
        <div className={styles.actions}>
          {desktopShell && persistent ? <VButton variant="secondary" density="compact" isDisabled={recovering} isPending={recovering} onPress={onRecover}>
            {recovering ? (zh ? "正在恢复工作台" : "Recovering workbench") : (zh ? "恢复工作台" : "Recover workbench")}
          </VButton> : null}
          <VButton variant="ghost" density="compact" isDisabled={recovering} onPress={onRetry}>{zh ? "检查连接" : "Check connection"}</VButton>
        </div>
      </section>
    </VPopover>
  );
}
