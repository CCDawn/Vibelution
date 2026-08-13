import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestBranchInstanceCleanup, type LauncherBranchInstance } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { VButton, VCheckbox, VConfirmDialog, VDenseTable, VTooltip } from "../components/vui";
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
      <VDenseTable
        ariaLabel={copy.branchInstances}
        className={styles.statusTable}
        resizable
        rows={paged.items}
        getRowKey={(item) => item.id}
        onRowClick={(item) => onSelect(item.id)}
        getRowState={(item) => {
          const health = instanceHealth(item, live);
          return {
            selected: item.id === selectedId,
            tone: health === "running" ? "success" : health === "dirty" ? "warning" : "neutral",
          };
        }}
        columns={[
          {
            id: "select",
            header: (
              <VCheckbox
                aria-label={labels.selectPage}
                isSelected={allPageSelected}
                isDisabled={pageEligible.length === 0}
                onChange={togglePage}
              />
            ),
            align: "center",
            width: 36,
            minWidth: 36,
            resizable: false,
            truncate: false,
            className: styles.selectCell,
            render: (item) => {
              const eligible = isCleanupEligible(item);
              return (
                <span onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                  <VCheckbox
                    aria-label={`${labels.cleanup} ${item.shortName || item.branch || item.id}`}
                    isSelected={eligible && visibleSelected.includes(item.id)}
                    isDisabled={!eligible}
                    onChange={(next) => toggleSelected(item, next)}
                  />
                </span>
              );
            },
          },
          {
            id: "branch",
            header: copy.branchColumn,
            width: 188,
            minWidth: 96,
            render: (item) => (
              <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
                <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>
              </VTooltip>
            ),
          },
          {
            id: "state",
            header: copy.instanceState,
            width: 88,
            minWidth: 64,
            render: (item) => instanceHealthLabel(instanceHealth(item, live), zh),
          },
          {
            id: "backend",
            header: labels.backend,
            width: 112,
            minWidth: 72,
            render: (item) => formatBackendCell(item, live),
          },
          {
            id: "window",
            header: labels.window,
            width: 56,
            minWidth: 44,
            render: (item) => (instanceWindowOpen(item, live) ? labels.windowOpen : labels.windowClosed),
          },
          {
            id: "path",
            header: copy.instancePath,
            width: 220,
            minWidth: 96,
            render: (item) => item.displayPath || "-",
          },
          {
            id: "actions",
            header: labels.actions,
            align: "right",
            width: 176,
            minWidth: 120,
            truncate: false,
            className: styles.actionCell,
            render: (item) => {
              const eligible = isCleanupEligible(item);
              return (
                <span className={styles.actionButtons} onClick={(event) => event.stopPropagation()}>
                  {canStartInstance(item, live) ? (
                    <VButton type="button" variant="primary" density="compact" isDisabled={lifecyclePending} onPress={() => onLifecycle?.(item.id, "start")}>
                      {labels.start}
                    </VButton>
                  ) : null}
                  {canStopInstance(item, live) ? (
                    <VButton type="button" variant="secondary" density="compact" isDisabled={lifecyclePending} onPress={() => onLifecycle?.(item.id, "stop")}>
                      {labels.stop}
                    </VButton>
                  ) : null}
                  {eligible ? (
                    <VButton type="button" variant="danger" density="compact" isDisabled={cleanupMutation.isPending} onPress={() => askCleanup([item.id])}>
                      {labels.cleanup}
                    </VButton>
                  ) : null}
                </span>
              );
            },
          },
        ]}
      />
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
