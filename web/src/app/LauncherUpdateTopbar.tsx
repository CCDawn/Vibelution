import { useMutation, useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { getLauncherFreshness, restartLatestLauncher } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { VButton, VConfirmDialog } from "../components/vui";
import styles from "./LauncherUpdateTopbar.styles";
import { isLauncherUpdateAvailable, LAUNCHER_UPDATE_MUTATION_KEY } from "./updateBanner";
import { refreshUpdateFreshness, UPDATE_FRESHNESS_INTERVAL_MS, UPDATE_FRESHNESS_QUERY_OPTIONS, useUpdateFreshnessFocus } from "./updateFreshness";

export function LauncherUpdateTopbar({ lang }: { lang: "zh" | "en" }) {
  const zh = lang === "zh";
  const [confirming, setConfirming] = useState(false);
  const updateLock = useRef(false);
  const queryClient = useQueryClient();
  const updateAttempts = useMutationState({ filters: { mutationKey: LAUNCHER_UPDATE_MUTATION_KEY }, select: (mutation) => mutation.state });
  const lastAttempt = updateAttempts.at(-1);
  const acceptedAt = lastAttempt?.status === "success"
    ? (lastAttempt.data as { acceptedAt?: number } | undefined)?.acceptedAt ?? lastAttempt.submittedAt : null;
  useUpdateFreshnessFocus(queryClient, !confirming && !updateLock.current);
  const freshnessQuery = useQuery({
    ...UPDATE_FRESHNESS_QUERY_OPTIONS,
    queryKey: queryKeys.launcherFreshness(),
    queryFn: getLauncherFreshness,
    // Acceptance schedules the replacement; only a later native read can
    // establish that it finished or returned to idle without replacing us.
    refetchInterval: (query) => confirming || updateLock.current ? false
      : acceptedAt !== null && (query.state.dataUpdatedAt <= acceptedAt || query.state.data?.updateInProgress !== false)
        ? 5_000 : UPDATE_FRESHNESS_INTERVAL_MS,
    refetchOnWindowFocus: confirming || updateLock.current ? false : "always",
    retry: false,
  });
  const updateMutation = useMutation({
    mutationKey: LAUNCHER_UPDATE_MUTATION_KEY,
    mutationFn: async () => {
      const result = await restartLatestLauncher();
      if (!result.accepted) throw new Error(result.message || (zh ? "更新未被接受，请重新检测。" : "Update was not accepted. Check again."));
      return { ...result, acceptedAt: Date.now() };
    },
    onSettled: () => { updateLock.current = false; void refreshUpdateFreshness(queryClient); },
  });

  const freshness = freshnessQuery.data;
  const hasUpdate = isLauncherUpdateAvailable(freshness);
  const settledAfterAcceptance = acceptedAt !== null && !freshnessQuery.isError
    && freshnessQuery.dataUpdatedAt > acceptedAt && freshness?.updateInProgress === false;
  const awaitingReplacement = acceptedAt !== null && !settledAfterAcceptance;
  const busy = updateMutation.isPending || lastAttempt?.status === "pending" || awaitingReplacement || freshness?.updateInProgress === true;
  const failure = (lastAttempt?.status === "error" && lastAttempt.error instanceof Error ? lastAttempt.error.message : "") || freshness?.refreshError
    || (awaitingReplacement && freshnessQuery.isError ? (zh ? "暂时无法确认更新状态，请重新检测。" : "Update status is unavailable. Please check again.") : "")
    || (settledAfterAcceptance && hasUpdate ? (zh ? "更新未完成，Launcher 仍在运行旧版本。请重试。" : "The update did not finish. Launcher is still running the previous version. Please retry.") : "");
  const unknown = freshnessQuery.isError || (!hasUpdate && freshness?.current !== true);
  const checking = freshnessQuery.isFetching && unknown;
  const active = freshness?.activeWorkState === "active";
  const taskUnknown = freshness?.activeWorkState !== "idle" && !active;
  const status = awaitingReplacement && freshnessQuery.isError ? (zh ? "无法确认更新状态" : "Update status unavailable")
    : busy ? (zh ? "准备中" : "Preparing")
    : checking ? (zh ? "正在检测" : "Checking")
      : unknown ? (zh ? "无法确认版本" : "Version unavailable")
        : failure ? (zh ? "更新失败" : "Update failed")
          : hasUpdate ? (freshness?.availableBuildState === "not_built"
            ? (zh ? "有更新，待构建" : "Update requires a build") : (zh ? "发现更新" : "Update available"))
            : (zh ? "已是最新版本" : "Up to date");
  const notice = active
    ? (zh ? `有 ${freshness?.activeWorkCount || 1} 个进行中的任务。更新会中断任务并保存已有记录，启动后可回到会话继续。` : "Updating will interrupt active tasks and save existing records. You can return to the conversation after restart.")
    : taskUnknown ? (zh ? "暂时无法确认任务状态。更新会中断任务并保存已有记录。" : "Task status is unavailable. Updating interrupts tasks and saves existing records.")
      : (zh ? "更新会保存已有任务记录并重启。" : "Updating saves existing task records and restarts.");

  return <div className={styles.pageContent}>
    <div role="status" aria-live="polite" className={styles.pageStatus}>{status}</div>
    <dl className={styles.versions}>
      <dt className={styles.metadata}>{zh ? "当前版本" : "Current version"}</dt><dd className={styles.version} title={freshness?.runningBuild?.id}>{freshness?.runningBuild ? `${zh ? "桌面构建" : "Desktop build"} ${freshness.runningBuild.id.slice(0, 12)}` : (zh ? "未知" : "Unknown")}</dd>
      <dt className={styles.metadata}>{zh ? "可用版本" : "Available version"}</dt><dd className={styles.version} title={freshness?.availableBuild?.id}>{freshness?.availableBuildState === "ready" && freshness.availableBuild
        ? `${zh ? "桌面构建" : "Desktop build"} ${freshness.availableBuild.id.slice(0, 12)}`
        : freshness?.availableBuildState === "not_built" ? (zh ? "待构建" : "Not built yet") : (zh ? "未知" : "Unknown")}</dd>
    </dl>
    {failure ? <p className={styles.failure} role="alert">{failure}</p> : null}
    <div className={styles.pageActions}>
      {busy || (!unknown && (hasUpdate || failure))
        ? <VButton variant="primary" isPending={busy} isDisabled={busy} onPress={() => setConfirming(true)}>{busy ? (zh ? "准备中…" : "Preparing…") : failure ? (zh ? "重试更新" : "Retry update") : (zh ? "更新并重启" : "Update and restart")}</VButton>
        : <VButton variant="primary" isPending={freshnessQuery.isFetching} onPress={() => { void refreshUpdateFreshness(queryClient); }}>{zh ? "重新检测" : "Check again"}</VButton>}
      {awaitingReplacement && freshnessQuery.isError ? <VButton isPending={freshnessQuery.isFetching} onPress={() => { void refreshUpdateFreshness(queryClient); }}>{zh ? "重新检测" : "Check again"}</VButton> : null}
    </div>
    <VConfirmDialog open={confirming} onOpenChange={setConfirming} title={zh ? "更新并重启？" : "Update and restart?"} description={notice} confirmLabel={zh ? "确认更新" : "Confirm update"} cancelLabel={zh ? "取消" : "Cancel"} onConfirm={() => {
      setConfirming(false);
      if (updateLock.current || busy) return;
      updateLock.current = true;
      updateMutation.mutate();
    }} />
  </div>;
}
