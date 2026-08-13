import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestBranchInstanceCleanup, type LauncherBranchInstance } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { VButton, VCheckbox, VConfirmDialog, VTooltip } from "../components/vui";
import type { LauncherOperation } from "../api/types";
import {
  BRANCH_INSTANCE_PAGE_SIZE,
  canStartInstance,
  canStopInstance,
  cleanupRiskLabels,
  formatBackendCell,
  instanceHealth,
  instanceHealthLabel,
  instanceWindowOpen,
  isCleanupEligible,
  paginateItems,
  type InstanceLiveOverlay,
} from "./LauncherBranchInstancesPanel.model";
import styles from "./LauncherBranchInstancesPanel.styles";

type LauncherBranchInstancesCopy = {
  branchInstances: string;
  branchInstancesHint: string;
  branchColumn: string;
  instanceState: string;
  instanceKind: string;
  instancePath: string;
  currentInstance: string;
  legacyCheckout: string;
  retiredCheckout: string;
  notCheckedOut: string;
};

type LauncherBranchInstancesPanelProps = {
  copy: LauncherBranchInstancesCopy;
  items: LauncherBranchInstance[];
  selectedId: string;
  onSelect: (id: string) => void;
  live?: InstanceLiveOverlay;
  lifecyclePending?: boolean;
  onLifecycle?: (instanceId: string, operation: Extract<LauncherOperation, "start" | "stop">) => void;
};

function isZhCopy(copy: LauncherBranchInstancesCopy): boolean {
  return copy.branchInstances !== "Branch instances";
}

export function LauncherBranchInstancesPanel({
  copy,
  items,
  selectedId,
  onSelect,
  live,
  lifecyclePending = false,
  onLifecycle,
}: LauncherBranchInstancesPanelProps) {
  const queryClient = useQueryClient();
  const zh = isZhCopy(copy);
  const labels = zh
    ? {
        cleanup: "清理",
        cleanupSelected: "清理所选",
        cleanupConfirmTitle: "确认清理分支实例",
        cleanupConfirmHint: "只删除本地 worktree 和本地分支，不会删除远端。",
        previous: "上一页",
        next: "下一页",
        selectPage: "选择本页可清理项",
        actions: "操作",
        backend: "后端",
        window: "窗口",
        windowOpen: "开",
        windowClosed: "关",
        start: "启动",
        stop: "停止",
        noRisk: "无额外风险提示",
        pending: "正在清理所选实例…",
        done: "清理完成",
        failed: "部分实例未能清理",
      }
    : {
        cleanup: "Clean up",
        cleanupSelected: "Clean up selected",
        cleanupConfirmTitle: "Confirm branch cleanup",
        cleanupConfirmHint: "This deletes local worktrees and local branches only. Remotes are not deleted.",
        previous: "Previous",
        next: "Next",
        selectPage: "Select cleanable items on this page",
        actions: "Actions",
        backend: "Backend",
        window: "Window",
        windowOpen: "On",
        windowClosed: "Off",
        start: "Start",
        stop: "Stop",
        noRisk: "No extra risk listed",
        pending: "Cleaning selected instances…",
        done: "Cleanup finished",
        failed: "Some instances could not be cleaned",
      };

  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [pendingIds, setPendingIds] = useState<string[] | null>(null);
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"neutral" | "error">("neutral");

  const paged = useMemo(() => paginateItems(items, page, BRANCH_INSTANCE_PAGE_SIZE), [items, page]);
  useEffect(() => {
    if (paged.page !== page) {
      setPage(paged.page);
    }
  }, [page, paged.page]);
  useEffect(() => {
    const index = items.findIndex((item) => item.id === selectedId);
    if (index < 0) {
      return;
    }
    const nextPage = Math.floor(index / BRANCH_INSTANCE_PAGE_SIZE) + 1;
    setPage((current) => (current === nextPage ? current : nextPage));
    // Jump only when the bound row changes, not on every list refresh.
  }, [selectedId, items.length]);

  const knownIds = useMemo(() => new Set(items.map((item) => item.id)), [items]);
  const visibleSelected = selectedIds.filter((id) => knownIds.has(id) && items.some((item) => item.id === id && isCleanupEligible(item)));
  const pageEligible = paged.items.filter(isCleanupEligible);
  const pageSelectedCount = pageEligible.filter((item) => visibleSelected.includes(item.id)).length;
  const allPageSelected = pageEligible.length > 0 && pageSelectedCount === pageEligible.length;

  const pendingItems = pendingIds
    ? items.filter((item) => pendingIds.includes(item.id))
    : [];

  const cleanupMutation = useMutation({
    mutationFn: (instanceIds: string[]) => requestBranchInstanceCleanup(instanceIds, true),
    onSuccess: (payload) => {
      const failed = [...payload.failed, ...payload.skipped];
      setNotice(failed.length > 0 ? `${labels.failed}：${failed.map((item) => item.shortName || item.id).join("、")}` : labels.done);
      setNoticeTone(failed.length > 0 ? "error" : "neutral");
      setSelectedIds((current) => current.filter((id) => !payload.cleaned.some((item) => item.id === id)));
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherBranchInstances() });
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : labels.failed);
      setNoticeTone("error");
    },
    onSettled: () => {
      setPendingIds(null);
    },
  });

  const toggleSelected = (item: LauncherBranchInstance, next: boolean) => {
    if (!isCleanupEligible(item)) {
      return;
    }
    setSelectedIds((current) => {
      if (next) {
        return current.includes(item.id) ? current : [...current, item.id];
      }
      return current.filter((id) => id !== item.id);
    });
  };

  const togglePage = (next: boolean) => {
    const pageIds = pageEligible.map((item) => item.id);
    setSelectedIds((current) => {
      if (next) {
        return [...new Set([...current, ...pageIds])];
      }
      return current.filter((id) => !pageIds.includes(id));
    });
  };

  const askCleanup = (ids: string[]) => {
    const eligible = items.filter((item) => ids.includes(item.id) && isCleanupEligible(item)).map((item) => item.id);
    if (eligible.length === 0) {
      return;
    }
    setNotice("");
    setPendingIds(eligible);
  };

  return (
    <section className={styles.panel} data-vui-region="launcher-branch-instances" aria-label={copy.branchInstances}>
      <div className={styles.panelHeader}>
        <p className={styles.panelEyebrow}>{copy.branchInstances}</p>
        <strong>{copy.branchInstancesHint}</strong>
      </div>
      <div className={styles.toolbar}>
        <div className={styles.toolbarActions}>
          <VButton
            type="button"
            variant="danger"
            density="compact"
            isDisabled={visibleSelected.length === 0 || cleanupMutation.isPending}
            onPress={() => askCleanup(visibleSelected)}
          >
            {labels.cleanupSelected}
            {visibleSelected.length > 0 ? ` (${visibleSelected.length})` : ""}
          </VButton>
          {notice ? <span className={noticeTone === "error" ? styles.noticeError : styles.notice}>{notice}</span> : null}
        </div>
        <div className={styles.pager} aria-label={copy.branchInstances}>
          <span className={styles.rangeLabel}>
            {paged.start + (paged.items.length > 0 ? 1 : 0)}-{paged.end} / {items.length}
          </span>
          <VButton type="button" density="compact" variant="secondary" isDisabled={paged.page <= 1} onPress={() => setPage((current) => current - 1)}>
            {labels.previous}
          </VButton>
          <strong>{paged.page}/{paged.pageCount}</strong>
          <VButton type="button" density="compact" variant="secondary" isDisabled={paged.page >= paged.pageCount} onPress={() => setPage((current) => current + 1)}>
            {labels.next}
          </VButton>
        </div>
      </div>
      <div className={styles.statusTable} role="table" aria-label={copy.branchInstances}>
        <div className={styles.statusHead} role="row">
          <span role="columnheader" className={styles.selectCell}>
            <VCheckbox
              aria-label={labels.selectPage}
              isSelected={allPageSelected}
              isDisabled={pageEligible.length === 0}
              onChange={togglePage}
            />
          </span>
          <span role="columnheader">{copy.branchColumn}</span>
          <span role="columnheader">{copy.instanceState}</span>
          <span role="columnheader">{labels.backend}</span>
          <span role="columnheader">{labels.window}</span>
          <span role="columnheader">{copy.instancePath}</span>
          <span role="columnheader">{labels.actions}</span>
        </div>
        {paged.items.map((item) => {
          const selected = item.id === selectedId;
          const eligible = isCleanupEligible(item);
          const checked = eligible && visibleSelected.includes(item.id);
          const health = instanceHealth(item, live);
          const windowOpen = instanceWindowOpen(item, live);
          return (
            <div
              key={item.id}
              className={styles.statusRow}
              role="row"
              tabIndex={0}
              data-tone={health === "running" ? "success" : health === "dirty" ? "warning" : "neutral"}
              data-selected={selected ? "true" : "false"}
              aria-selected={selected}
              onClick={() => onSelect(item.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(item.id);
                }
              }}
            >
              <span role="cell" className={styles.selectCell} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                <VCheckbox
                  aria-label={`${labels.cleanup} ${item.shortName || item.branch || item.id}`}
                  isSelected={checked}
                  isDisabled={!eligible}
                  onChange={(next) => toggleSelected(item, next)}
                />
              </span>
              <span role="cell">
                <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
                  <strong>{item.shortName || item.branch || item.id}</strong>
                </VTooltip>
              </span>
              <span role="cell">{instanceHealthLabel(health, zh)}</span>
              <span role="cell">{formatBackendCell(item, live)}</span>
              <span role="cell">{windowOpen ? labels.windowOpen : labels.windowClosed}</span>
              <span role="cell">{item.displayPath || "-"}</span>
              <span role="cell" className={styles.actionCell} onClick={(event) => event.stopPropagation()}>
                {canStartInstance(item, live) ? (
                  <VButton
                    type="button"
                    variant="primary"
                    density="compact"
                    isDisabled={lifecyclePending}
                    onPress={() => onLifecycle?.(item.id, "start")}
                  >
                    {labels.start}
                  </VButton>
                ) : null}
                {canStopInstance(item, live) ? (
                  <VButton
                    type="button"
                    variant="secondary"
                    density="compact"
                    isDisabled={lifecyclePending}
                    onPress={() => onLifecycle?.(item.id, "stop")}
                  >
                    {labels.stop}
                  </VButton>
                ) : null}
                {eligible ? (
                  <VButton
                    type="button"
                    variant="danger"
                    density="compact"
                    isDisabled={cleanupMutation.isPending}
                    onPress={() => askCleanup([item.id])}
                  >
                    {labels.cleanup}
                  </VButton>
                ) : null}
              </span>
            </div>
          );
        })}
      </div>
      <VConfirmDialog
        open={pendingIds !== null}
        onOpenChange={(open) => {
          if (!open && !cleanupMutation.isPending) {
            setPendingIds(null);
          }
        }}
        title={labels.cleanupConfirmTitle}
        description={labels.cleanupConfirmHint}
        tone="danger"
        size="md"
        confirmLabel={labels.cleanup}
        cancelLabel={zh ? "取消" : "Cancel"}
        confirmPending={cleanupMutation.isPending}
        confirmDisabled={pendingItems.length === 0}
        onConfirm={() => {
          if (pendingIds && pendingIds.length > 0) {
            cleanupMutation.mutate(pendingIds);
          }
        }}
      >
        <ul className={styles.confirmList}>
          {pendingItems.map((item) => {
            const risks = cleanupRiskLabels(item, zh);
            return (
              <li key={item.id} className={styles.confirmItem}>
                <p className={styles.confirmName}>{item.shortName || item.branch || item.id}</p>
                <p className={styles.confirmPath}>{item.path || item.displayPath || item.branch || item.id}</p>
                <ul className={styles.confirmRisks}>
                  {(risks.length > 0 ? risks : [labels.noRisk]).map((risk) => (
                    <li key={risk}>{risk}</li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      </VConfirmDialog>
    </section>
  );
}
