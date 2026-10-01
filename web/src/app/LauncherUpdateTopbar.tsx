import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowUpCircle, Check, ChevronDown, GitBranch, LoaderCircle, Monitor, RefreshCw } from "lucide-react";
import { useRef, useState } from "react";

import { getLauncherFreshness, restartLatestLauncher } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import type { LauncherFreshness } from "../api/types";
import { VButton, VPopover, VToolbar } from "../components/vui";
import styles from "./LauncherUpdateTopbar.styles";

export type LauncherUpdateTopbarViewProps = {
  lang: "zh" | "en";
  branchName?: string;
  freshness?: LauncherFreshness;
  checking: boolean;
  checkFailed: boolean;
  updating: boolean;
  error?: string;
  onCheck: () => void;
  onUpdate: () => void;
  onDetailsChange?: (open: boolean) => void;
};

/** Shared chrome for both Launcher routes; closing details never dismisses the reminder. */
export function LauncherUpdateTopbarView({
  lang, branchName, freshness, checking, checkFailed, updating, error,
  onCheck, onUpdate, onDetailsChange,
}: LauncherUpdateTopbarViewProps) {
  const zh = lang === "zh";
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const hasUpdate = Boolean(freshness && (freshness.updateAvailable || freshness.current === false || freshness.shellStale));
  const busy = updating || freshness?.updateInProgress === true;
  const failure = error || freshness?.refreshError || "";
  const unknown = checkFailed || !freshness || (freshness.current === null && !hasUpdate);
  const active = freshness?.activeWorkState === "active";
  const taskUnknown = freshness?.activeWorkState !== "idle" && !active;
  const disabled = checking || checkFailed || taskUnknown || active;
  const label = busy ? (zh ? "正在更新…" : "Updating…")
    : failure ? (zh ? "更新失败 · 重试" : "Update failed · Retry")
      : hasUpdate ? (zh ? "有新版本 · 请更新" : "Update available")
        : checking ? (zh ? "正在检测版本…" : "Checking version…")
          : unknown ? (zh ? "版本检测失败" : "Version unavailable")
            : (zh ? "已是最新版本" : "Up to date");
  const title = busy ? (zh ? "正在准备新版 Launcher" : "Preparing the latest Launcher")
    : failure ? (zh ? "更新未完成，当前版本仍可使用" : "Update incomplete; the current version is still available")
      : hasUpdate ? (zh ? "新版 Launcher 已就绪" : "A newer Launcher is available")
        : unknown ? (zh ? "暂时无法确认版本" : "Unable to confirm the version")
          : (zh ? "Launcher 已是最新版本" : "Launcher is up to date");
  const changeOpen = (value: boolean) => {
    setOpen(value);
    if (!value) setConfirm(false);
    onDetailsChange?.(value);
  };

  return (
    <VToolbar ariaLabel={zh ? "Launcher 顶栏" : "Launcher top bar"} wrap={false} className={styles.toolbar} data-testid="launcher-topbar">
      <Monitor size={16} className={styles.appIcon} aria-hidden="true" />
      <strong className={styles.title}>Vibelution <span className={styles.launcherName}>Launcher</span></strong>
      {branchName ? <span className={styles.branch}><GitBranch size={13} aria-hidden="true" />{branchName}</span> : null}
      <div className={styles.spacer} />
      <VPopover open={open} onOpenChange={changeOpen} side="bottom" align="end" sideOffset={8}
        aria-label={zh ? "Launcher 更新详情" : "Launcher update details"} contentClassName={styles.popover}
        trigger={<VButton variant="ghost" contentLayout="plain" className={`${styles.button} ${styles.trigger} ${hasUpdate || failure ? styles.updateTone : styles.mutedTone}`} aria-label={label} data-testid="launcher-update-trigger">
          {busy || checking ? <LoaderCircle size={14} className={styles.spinner} aria-hidden="true" />
            : hasUpdate || failure ? <ArrowUpCircle size={14} aria-hidden="true" />
              : unknown ? <RefreshCw size={14} aria-hidden="true" /> : <Check size={14} aria-hidden="true" />}
          <span>{label}</span><ChevronDown size={12} aria-hidden="true" />
        </VButton>}>
        <div className={styles.content} role="status" aria-live="polite">
          <div className={styles.heading}>
            <strong className={styles.headingTitle}>{title}</strong>
            <p className={styles.description}>{unknown && !hasUpdate
              ? (zh ? "检测失败不代表已经是最新版本，请稍后重新检测。" : "A failed check does not mean you are up to date. Please check again.")
              : (zh ? "桌面壳和启动器前端一起检查，与本地最新代码比较。工作区配置不会改变。" : "The desktop shell and Launcher frontend are compared with local code. Workspace settings are preserved.")}</p>
          </div>
          {freshness && (hasUpdate || freshness.runningShort || freshness.headShort) ? <dl className={styles.versions}>
            <dt className={styles.metadata}>{zh ? "当前版本" : "Running"}</dt><dd className={styles.version}>{freshness.runningShort ? `@${freshness.runningShort}` : (zh ? "未知" : "Unknown")}</dd>
            <dt className={styles.metadata}>{zh ? "本地最新" : "Local code"}</dt><dd className={styles.version}>{freshness.headShort ? `@${freshness.headShort}` : (zh ? "未知" : "Unknown")}</dd>
          </dl> : null}
          {active ? <p className={`${styles.description} ${styles.warning}`}>{zh ? `有 ${freshness?.activeWorkCount || 1} 个进行中的任务。请等待任务完成后更新，当前不会重启。` : "Active tasks block updates. Wait until they finish; no restart will occur."}</p> : null}
          {hasUpdate && taskUnknown && !busy ? <p className={`${styles.description} ${styles.warning}`}>{zh ? "暂时无法确认任务状态，更新已暂停。请重新检测。" : "Task status is unavailable. Updates are paused; please check again."}</p> : null}
          {busy ? <p className={`${styles.description} ${styles.busyDescription}`}><LoaderCircle size={14} className={styles.busyIcon} aria-hidden="true" />{zh ? "正在构建前端和桌面壳。准备完成后关闭窗口，在后台完成换版并重新打开。" : "Building the frontend and desktop shell. The windows will close for final replacement and reopen afterwards."}</p> : null}
          {failure ? <p className={`${styles.description} ${styles.failure}`}>{failure}</p> : null}
          {confirm && !busy ? <div className={styles.confirmation}>
            <p className={styles.description}>{zh ? "更新会关闭 Launcher 和工作区窗口。确认当前任务已结束？" : "Updating closes Launcher and workbench windows. Have all tasks finished?"}</p>
            <div className={styles.actions}>
              <VButton className={styles.button} variant="ghost" onPress={() => setConfirm(false)}>{zh ? "取消" : "Cancel"}</VButton>
              <VButton className={styles.button} variant="primary" isDisabled={disabled} onPress={() => { setConfirm(false); onUpdate(); }}>{zh ? "确认更新" : "Confirm update"}</VButton>
            </div>
          </div> : <div className={styles.actions}>
            <VButton className={styles.button} variant="ghost" onPress={() => changeOpen(false)}>{zh ? "关闭详情" : "Close details"}</VButton>
            {!busy ? <VButton className={styles.button} variant="ghost" isPending={checking} onPress={onCheck}>{zh ? "重新检测" : "Check again"}</VButton> : null}
            {hasUpdate || failure ? <VButton className={styles.button} variant="primary" isPending={busy} isDisabled={disabled || unknown} onPress={() => setConfirm(true)}>
              {busy ? (zh ? "正在更新…" : "Updating…") : active ? (zh ? "任务完成后更新" : "Wait for tasks") : failure ? (zh ? "重试更新" : "Retry update") : (zh ? "更新并重启" : "Update and restart")}
            </VButton> : null}
          </div>}
          <span className={styles.metadata}>{zh ? "关闭详情后，顶栏更新提示仍保留。" : "Closing details keeps the top bar reminder visible."}</span>
        </div>
      </VPopover>
    </VToolbar>
  );
}

export function LauncherUpdateTopbar({ lang, branchName }: Pick<LauncherUpdateTopbarViewProps, "lang" | "branchName">) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const updateLock = useRef(false);
  const freshnessQuery = useQuery({
    queryKey: queryKeys.launcherFreshness(),
    queryFn: getLauncherFreshness,
    refetchInterval: detailsOpen ? 5_000 : 60_000,
    retry: false,
  });
  const updateMutation = useMutation({
    mutationFn: async () => {
      const result = await restartLatestLauncher();
      if (!result.accepted) throw new Error(result.message || (lang === "zh" ? "更新未被接受，请重新检测。" : "Update was not accepted. Check again."));
      return result;
    },
    onSuccess: () => setAccepted(true),
    onSettled: () => { updateLock.current = false; void freshnessQuery.refetch(); },
  });
  return <LauncherUpdateTopbarView lang={lang} branchName={branchName} freshness={freshnessQuery.data}
    checking={freshnessQuery.isFetching} checkFailed={freshnessQuery.isError}
    updating={updateMutation.isPending || accepted}
    error={updateMutation.error instanceof Error ? updateMutation.error.message : undefined}
    onCheck={() => { updateMutation.reset(); void freshnessQuery.refetch(); }}
    onUpdate={() => {
      if (updateLock.current || accepted) return;
      updateLock.current = true;
      updateMutation.mutate();
    }}
    onDetailsChange={(open) => { setDetailsOpen(open); if (open) void freshnessQuery.refetch(); }} />;
}
