import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, LoaderCircle, StopCircle } from "lucide-react";
import { useEffect, useState } from "react";

import {
  childSessionHref,
  listRuntimeTasksRevisionAware,
  stopRuntimeTask,
  type RuntimeTaskCard,
  type RuntimeTaskListPayload,
} from "../../api/runtimeTasks";
import { queryKeys } from "../../api/queryKeys";
import { resolvePollingInterval, usePageVisibility } from "../../app/pollingPolicy";
import { useShellI18n } from "../../i18n/useShellI18n";
import { auxTaskKindLabel } from "../../routes/auxConversations/auxTaskPresentation";
import { VButton, VChip, VConfirmDialog, VRouteLinkButton } from "../vui";
import styles from "./ConversationRunningTasks.styles";
import { activeTurnElapsedSeconds } from "./conversationActiveTurnStatusPresentation";

/** Foreground poll beat; hidden conversation panes stop polling. */
export const CONVERSATION_RUNNING_TASKS_POLL_MS = 4_000;

/** Fallback jump target for tasks that do not own a child session. */
const AUX_CENTER_HREF = "/aux";

const COPY = {
  zh: {
    section: "后台任务",
    open: "打开",
    ended: "已结束",
    stop: "停止",
    stopPending: "停止中…",
    stopConfirmTitle: "停止该任务？",
    stopConfirmDescription: "停止后任务将结束运行，已产生的结果保留。",
    stopFailed: "停止请求失败",
    cancel: "取消",
  },
  en: {
    section: "Background tasks",
    open: "Open",
    ended: "Ended",
    stop: "Stop",
    stopPending: "Stopping…",
    stopConfirmTitle: "Stop this task?",
    stopConfirmDescription: "The task will stop running; finished output is kept.",
    stopFailed: "Stop request failed",
    cancel: "Cancel",
  },
} as const;

/**
 * Tail-of-timeline strip for background runtime tasks parented to the current
 * session (ZCode ConversationStatusPanel shape): one compact row per live task
 * with a jump-seconds elapsed counter and a stop action, plus a footer
 * directory row ("已结束 · N ›") into the aux center when this session has
 * ended tasks. Stop only records the intent — the row flips to 停止中… and the
 * polled list decides the terminal state (the row leaves the running bucket
 * once `endedAt` exists). With neither running rows nor an ended count the
 * strip renders null: zero placeholder, no layout tax.
 */
export function ConversationRunningTasks({ sessionId }: { sessionId: string }) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();

  const listKey = queryKeys.runtimeTasks("", sessionId);
  const listQuery = useQuery({
    queryKey: listKey,
    queryFn: ({ signal }) =>
      listRuntimeTasksRevisionAware(
        { status: "active", parentSessionId: sessionId },
        queryClient.getQueryData<RuntimeTaskListPayload>(listKey),
        signal,
      ),
    enabled: Boolean(sessionId),
    refetchInterval: resolvePollingInterval(pageVisible, CONVERSATION_RUNNING_TASKS_POLL_MS),
    refetchIntervalInBackground: false,
  });
  const runningTasks = listQuery.data?.running ?? [];

  // Ended directory count for the session (ZCode EndedDirectoryRow shape):
  // one page-one probe is enough — `ended.total` is the full ended count.
  const endedKey = queryKeys.runtimeTasks("ended", sessionId);
  const endedQuery = useQuery({
    queryKey: endedKey,
    queryFn: ({ signal }) =>
      listRuntimeTasksRevisionAware(
        { status: "ended", parentSessionId: sessionId, limit: 1 },
        queryClient.getQueryData<RuntimeTaskListPayload>(endedKey),
        signal,
      ),
    enabled: Boolean(sessionId),
    refetchInterval: resolvePollingInterval(pageVisible, CONVERSATION_RUNNING_TASKS_POLL_MS),
    refetchIntervalInBackground: false,
  });
  const endedTotal = endedQuery.data?.ended?.total ?? 0;

  // Stop only records the intent: the id stays "requested" until the polled
  // list drops the task from the running bucket, so the row shows 停止中…
  // meanwhile. `accepted:false` is not an error and stays unmarked.
  const [stopTargetId, setStopTargetId] = useState("");
  const [stopRequestedIds, setStopRequestedIds] = useState<readonly string[]>([]);
  const stopMutation = useMutation({
    mutationFn: (taskId: string) => stopRuntimeTask(taskId),
    onSuccess: (result) => {
      if (result.accepted) {
        setStopRequestedIds((current) =>
          current.includes(result.taskId) ? current : [...current, result.taskId],
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["runtime-tasks"] });
      setStopTargetId("");
    },
  });

  // Jump-seconds elapsed per row, billed from the card's own start stamp
  // (ActiveTurnStatusNote cadence); the 1s timer only runs while rows exist.
  const [nowMs, setNowMs] = useState(() => Date.now());
  const hasRunningTasks = runningTasks.length > 0;
  useEffect(() => {
    if (!hasRunningTasks) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [hasRunningTasks]);

  if (!hasRunningTasks && endedTotal <= 0) {
    return null;
  }

  const stopTargetTask = runningTasks.find((task) => task.taskId === stopTargetId) ?? null;

  return (
    <div
      className={styles.root}
      data-conversation-running-tasks="true"
      aria-label={copy.section}
    >
      {hasRunningTasks ? (
        <div className={styles.list}>
          {runningTasks.map((task) => (
            <RunningTaskRow
              key={task.taskId}
              task={task}
              lang={lang}
              nowMs={nowMs}
              stopRequested={stopRequestedIds.includes(task.taskId)}
              stopPending={stopMutation.isPending && stopMutation.variables === task.taskId}
              onAskStop={() => setStopTargetId(task.taskId)}
              copy={copy}
            />
          ))}
          {stopMutation.isError ? (
            <span role="alert">{stopMutation.error instanceof Error && stopMutation.error.message
              ? stopMutation.error.message
              : copy.stopFailed}</span>
          ) : null}
        </div>
      ) : null}
      {endedTotal > 0 ? (
        <VRouteLinkButton
          to={AUX_CENTER_HREF}
          variant="ghost"
          density="compact"
          className={styles.endedRow}
          data-testid="conversation-running-tasks-ended-row"
        >
          <CheckCircle2 size={14} className={styles.endedIcon} aria-hidden="true" />
          <span className={styles.endedLabel}>{copy.ended} · {endedTotal}</span>
          <ChevronRight size={14} className={styles.endedChevron} aria-hidden="true" />
        </VRouteLinkButton>
      ) : null}
      <VConfirmDialog
        open={Boolean(stopTargetTask)}
        onOpenChange={(open) => {
          if (!open) {
            setStopTargetId("");
          }
        }}
        tone="danger"
        title={copy.stopConfirmTitle}
        description={stopTargetTask?.title || copy.stopConfirmDescription}
        confirmLabel={copy.stop}
        cancelLabel={copy.cancel}
        confirmPending={stopMutation.isPending}
        onConfirm={() => {
          if (stopTargetId) {
            stopMutation.mutate(stopTargetId);
          }
        }}
      />
    </div>
  );
}

type RunningTasksCopy = Record<keyof (typeof COPY)["zh"], string>;

function RunningTaskRow({
  task,
  lang,
  nowMs,
  stopRequested,
  stopPending,
  onAskStop,
  copy,
}: {
  task: RuntimeTaskCard;
  lang: "zh" | "en";
  nowMs: number;
  stopRequested: boolean;
  stopPending: boolean;
  onAskStop: () => void;
  copy: RunningTasksCopy;
}) {
  const elapsedSeconds = activeTurnElapsedSeconds(task.startedAt, nowMs) ?? 0;
  const childSessionId = String(task.childSessionId || "").trim();
  const openHref = childSessionId
    ? childSessionHref(childSessionId)
    : AUX_CENTER_HREF;
  return (
    <div
      className={styles.row}
      data-testid={`conversation-running-task-${task.taskId}`}
      data-conversation-running-task-stop-requested={stopRequested ? "true" : undefined}
    >
      <LoaderCircle className={styles.spinner} size={14} aria-hidden="true" />
      <VChip tone="neutral" className={styles.kindChip}>
        {auxTaskKindLabel(task.kind, lang)}
      </VChip>
      <strong className={styles.title} title={task.title || task.taskId}>
        {task.title || task.taskId}
      </strong>
      <span className={styles.elapsed} data-testid={`conversation-running-task-elapsed-${task.taskId}`}>
        {elapsedSeconds}s
      </span>
      <span className={styles.actions}>
        <VRouteLinkButton
          to={openHref}
          variant="ghost"
          density="compact"
          className={styles.openLink}
          data-testid={`conversation-running-task-open-${task.taskId}`}
        >
          {copy.open}
        </VRouteLinkButton>
        <VButton
          variant="ghost"
          density="compact"
          className={styles.stopButton}
          isDisabled={stopRequested}
          isPending={stopPending}
          icon={<StopCircle size={14} aria-hidden="true" />}
          onPress={onAskStop}
          data-testid={`conversation-running-task-stop-${task.taskId}`}
        >
          {stopRequested ? copy.stopPending : copy.stop}
        </VButton>
      </span>
    </div>
  );
}
