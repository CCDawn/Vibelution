import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestBranchInstanceCleanup, type LauncherBranchInstance } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { VButton, VCheckbox, VConfirmDialog, VDenseTable, VStatusChip, VTooltip } from "../components/vui";
import type { LauncherOperation } from "../api/types";
import {
  BRANCH_INSTANCE_PAGE_SIZE,
  canRequestOpenInstance,
  canStopInstance,
  cleanupRiskLabels,
  formatBackendStatus,
  formatFrontendStatus,
  formatGitStatus,
  formatWorkbenchStatus,
  groupBranchInstances,
  instanceRuntimeState,
  instanceRuntimeStateLabel,
  instanceWindowOpen,
  isCleanupEligible,
  paginateItems,
  type InstancePendingOperation,
  type InstanceRuntimeState,
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
  pendingOperation?: InstancePendingOperation;
  launcherTitle?: string;
  launcherOnline?: boolean;
  lifecyclePending?: boolean;
  onLifecycle?: (instanceId: string, operation: Extract<LauncherOperation, "start" | "stop">) => void;
};

function isZhCopy(copy: LauncherBranchInstancesCopy): boolean {
  return copy.branchInstances !== "Branch instances";
}

function runtimeTone(state: InstanceRuntimeState): "neutral" | "success" | "warning" {
  if (state === "running") {
    return "success";
  }
  if (state === "partial" || state === "failed") {
    return "warning";
  }
  return "neutral";
}

export function LauncherBranchInstancesPanel({
  copy,
  items,
  selectedId,
  onSelect,
  pendingOperation,
  launcherTitle,
  launcherOnline = false,
  lifecyclePending = false,
  onLifecycle,
}: LauncherBranchInstancesPanelProps) {
  const queryClient = useQueryClient();
  const zh = isZhCopy(copy);
  const labels = zh
    ? {
        running: "正在运行",
        runningHint: "含启动中、部分运行和需要处理的实例",
        startable: "可启动",
        startableHint: "已具备 worktree，当前没有运行信号",
        maintenance: "维护与清理",
        controlWindow: "Launcher 控制窗口",
        online: "在线",
        offline: "未连接",
        emptyRunning: "当前没有运行中的分支",
        emptyStartable: "当前没有可启动的分支",
        cleanup: "清理",
        cleanupSelected: "清理所选",
        cleanupConfirmTitle: "确认清理分支实例",
        cleanupConfirmHint: "只删除本地 worktree 和本地分支，不会删除远端。",
        previous: "上一页",
        next: "下一页",
        selectPage: "选择本页可清理项",
        actions: "操作",
        backend: "后端",
        frontend: "前端",
        frontendMode: "前端模式",
        workbench: "Workbench 窗口",
        git: "Git",
        readiness: "启动准备",
        ready: "可以启动",
        startWorkbench: "启动工作台",
        openWindow: "打开窗口",
        focusWindow: "聚焦窗口",
        retryStart: "重新启动",
        stop: "停止",
        noRisk: "无额外风险提示",
        pending: "正在清理所选实例…",
        done: "清理完成",
        failed: "部分实例未能清理",
      }
    : {
        running: "Running",
        runningHint: "Includes starting, partially running, and attention-needed instances",
        startable: "Ready to start",
        startableHint: "Checked-out worktrees with no active runtime signal",
        maintenance: "Maintenance and cleanup",
        controlWindow: "Launcher control window",
        online: "Online",
        offline: "Disconnected",
        emptyRunning: "No branch is currently running",
        emptyStartable: "No branch is currently ready to start",
        cleanup: "Clean up",
        cleanupSelected: "Clean up selected",
        cleanupConfirmTitle: "Confirm branch cleanup",
        cleanupConfirmHint: "This deletes local worktrees and local branches only. Remotes are not deleted.",
        previous: "Previous",
        next: "Next",
        selectPage: "Select cleanable items on this page",
        actions: "Actions",
        backend: "Backend",
        frontend: "Frontend",
        frontendMode: "Frontend mode",
        workbench: "Workbench window",
        git: "Git",
        readiness: "Readiness",
        ready: "Ready to start",
        startWorkbench: "Start workbench",
        openWindow: "Open window",
        focusWindow: "Focus window",
        retryStart: "Retry start",
        stop: "Stop",
        noRisk: "No extra risk listed",
        pending: "Cleaning selected instances…",
        done: "Cleanup finished",
        failed: "Some instances could not be cleaned",
      };

  const [startablePage, setStartablePage] = useState(1);
  const [maintenancePage, setMaintenancePage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [pendingIds, setPendingIds] = useState<string[] | null>(null);
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"neutral" | "error">("neutral");

  const grouped = useMemo(() => groupBranchInstances(items, pendingOperation), [items, pendingOperation]);
  const maintenanceItems = useMemo(() => items.filter(isCleanupEligible), [items]);
  const pagedStartable = useMemo(
    () => paginateItems(grouped.startable, startablePage, BRANCH_INSTANCE_PAGE_SIZE),
    [grouped.startable, startablePage],
  );
  const pagedMaintenance = useMemo(
    () => paginateItems(maintenanceItems, maintenancePage, BRANCH_INSTANCE_PAGE_SIZE),
    [maintenanceItems, maintenancePage],
  );

  useEffect(() => {
    if (pagedStartable.page !== startablePage) {
      setStartablePage(pagedStartable.page);
    }
  }, [pagedStartable.page, startablePage]);
  useEffect(() => {
    if (pagedMaintenance.page !== maintenancePage) {
      setMaintenancePage(pagedMaintenance.page);
    }
  }, [maintenancePage, pagedMaintenance.page]);
  useEffect(() => {
    const startableIndex = grouped.startable.findIndex((item) => item.id === selectedId);
    if (startableIndex >= 0) {
      setStartablePage(Math.floor(startableIndex / BRANCH_INSTANCE_PAGE_SIZE) + 1);
    }
    const maintenanceIndex = maintenanceItems.findIndex((item) => item.id === selectedId);
    if (maintenanceIndex >= 0) {
      setMaintenancePage(Math.floor(maintenanceIndex / BRANCH_INSTANCE_PAGE_SIZE) + 1);
    }
  }, [grouped.startable, maintenanceItems, selectedId]);

  const knownIds = useMemo(() => new Set(items.map((item) => item.id)), [items]);
  const cleanupSelected = selectedIds.filter((id) => knownIds.has(id) && maintenanceItems.some((item) => item.id === id));
  const pageEligible = pagedMaintenance.items;
  const pageSelectedCount = pageEligible.filter((item) => cleanupSelected.includes(item.id)).length;
  const allPageSelected = pageEligible.length > 0 && pageSelectedCount === pageEligible.length;
  const pendingItems = pendingIds ? items.filter((item) => pendingIds.includes(item.id)) : [];

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
        <p className={styles.controlWindow} role="status">
          <span>{labels.controlWindow}</span>
          <strong>{launcherTitle || "-"}</strong>
          <VStatusChip tone={launcherOnline ? "success" : "warning"}>
            {launcherOnline ? labels.online : labels.offline}
          </VStatusChip>
        </p>
      </div>

      <section className={styles.instanceSection} aria-label={labels.running}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionTitleRow}>
            <h2>{labels.running}</h2>
            <span className={styles.sectionCount}>{grouped.running.length}</span>
          </div>
          <p>{labels.runningHint}</p>
        </div>
        <VDenseTable
          ariaLabel={labels.running}
          className={styles.statusTable}
          resizable
          rows={grouped.running}
          emptyText={labels.emptyRunning}
          getRowKey={(item) => item.id}
          onRowClick={(item) => onSelect(item.id)}
          getRowState={(item) => ({
            selected: item.id === selectedId,
            tone: runtimeTone(instanceRuntimeState(item, pendingOperation)),
          })}
          columns={[
            {
              id: "branch",
              header: copy.branchColumn,
              width: 210,
              minWidth: 120,
              render: (item) => (
                <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
                  <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>
                </VTooltip>
              ),
            },
            {
              id: "state",
              header: copy.instanceState,
              width: 104,
              minWidth: 88,
              render: (item) => {
                const state = instanceRuntimeState(item, pendingOperation);
                return (
                  <VStatusChip tone={runtimeTone(state)}>
                    {instanceRuntimeStateLabel(state, zh)}
                  </VStatusChip>
                );
              },
            },
            {
              id: "backend",
              header: labels.backend,
              width: 132,
              minWidth: 104,
              render: (item) => formatBackendStatus(item, zh),
            },
            {
              id: "frontend",
              header: labels.frontend,
              width: 138,
              minWidth: 112,
              render: (item) => formatFrontendStatus(item, zh),
            },
            {
              id: "workbench",
              header: labels.workbench,
              width: 230,
              minWidth: 160,
              fill: true,
              render: (item) => formatWorkbenchStatus(item, zh),
            },
            {
              id: "git",
              header: labels.git,
              width: 142,
              minWidth: 92,
              render: (item) => formatGitStatus(item, zh),
            },
            {
              id: "actions",
              header: labels.actions,
              align: "right",
              width: 188,
              minWidth: 148,
              truncate: false,
              className: styles.actionCell,
              render: (item) => {
                const state = instanceRuntimeState(item, pendingOperation);
                const windowOpen = instanceWindowOpen(item);
                const openLabel = state === "failed" ? labels.retryStart : windowOpen ? labels.focusWindow : labels.openWindow;
                return (
                  <span className={styles.actionButtons} onClick={(event) => event.stopPropagation()}>
                    {canRequestOpenInstance(item, pendingOperation) ? (
                      <VButton type="button" variant="primary" density="compact" isDisabled={lifecyclePending} onPress={() => onLifecycle?.(item.id, "start")}>
                        {openLabel}
                      </VButton>
                    ) : null}
                    {canStopInstance(item, pendingOperation) ? (
                      <VButton type="button" variant="secondary" density="compact" isDisabled={lifecyclePending} onPress={() => onLifecycle?.(item.id, "stop")}>
                        {labels.stop}
                      </VButton>
                    ) : null}
                  </span>
                );
              },
            },
          ]}
        />
      </section>

      <section className={styles.instanceSection} aria-label={labels.startable}>
        <div className={styles.sectionHeaderWithPager}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionTitleRow}>
              <h2>{labels.startable}</h2>
              <span className={styles.sectionCount}>{grouped.startable.length}</span>
            </div>
            <p>{labels.startableHint}</p>
          </div>
          <div className={styles.pager} aria-label={labels.startable}>
            <span className={styles.rangeLabel}>
              {pagedStartable.start + (pagedStartable.items.length > 0 ? 1 : 0)}-{pagedStartable.end} / {grouped.startable.length}
            </span>
            <VButton type="button" density="compact" variant="secondary" isDisabled={pagedStartable.page <= 1} onPress={() => setStartablePage((current) => current - 1)}>
              {labels.previous}
            </VButton>
            <strong>{pagedStartable.page}/{pagedStartable.pageCount}</strong>
            <VButton type="button" density="compact" variant="secondary" isDisabled={pagedStartable.page >= pagedStartable.pageCount} onPress={() => setStartablePage((current) => current + 1)}>
              {labels.next}
            </VButton>
          </div>
        </div>
        <VDenseTable
          ariaLabel={labels.startable}
          className={styles.statusTable}
          resizable
          rows={pagedStartable.items}
          emptyText={labels.emptyStartable}
          getRowKey={(item) => item.id}
          onRowClick={(item) => onSelect(item.id)}
          getRowState={(item) => ({ selected: item.id === selectedId, tone: "neutral" })}
          columns={[
            {
              id: "branch",
              header: copy.branchColumn,
              width: 230,
              minWidth: 120,
              render: (item) => (
                <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
                  <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>
                </VTooltip>
              ),
            },
            {
              id: "readiness",
              header: labels.readiness,
              width: 112,
              minWidth: 92,
              render: () => <VStatusChip tone="success">{labels.ready}</VStatusChip>,
            },
            {
              id: "frontend",
              header: labels.frontendMode,
              width: 150,
              minWidth: 120,
              render: (item) => formatFrontendStatus(item, zh),
            },
            {
              id: "git",
              header: labels.git,
              width: 160,
              minWidth: 100,
              render: (item) => formatGitStatus(item, zh),
            },
            {
              id: "path",
              header: copy.instancePath,
              width: 280,
              minWidth: 140,
              fill: true,
              render: (item) => item.displayPath || "-",
            },
            {
              id: "actions",
              header: labels.actions,
              align: "right",
              width: 142,
              minWidth: 120,
              truncate: false,
              className: styles.actionCell,
              render: (item) => (
                <span className={styles.actionButtons} onClick={(event) => event.stopPropagation()}>
                  <VButton type="button" variant="primary" density="compact" isDisabled={lifecyclePending} onPress={() => onLifecycle?.(item.id, "start")}>
                    {labels.startWorkbench}
                  </VButton>
                </span>
              ),
            },
          ]}
        />
      </section>

      <details className={styles.maintenanceFold}>
        <summary>
          <span>{labels.maintenance}</span>
          <strong>{maintenanceItems.length}</strong>
        </summary>
        <div className={styles.maintenanceBody}>
          <div className={styles.toolbar}>
            <div className={styles.toolbarActions}>
              <VButton
                type="button"
                variant="danger"
                density="compact"
                isDisabled={cleanupSelected.length === 0 || cleanupMutation.isPending}
                onPress={() => askCleanup(cleanupSelected)}
              >
                {labels.cleanupSelected}
                {cleanupSelected.length > 0 ? ` (${cleanupSelected.length})` : ""}
              </VButton>
              {notice ? <span className={noticeTone === "error" ? styles.noticeError : styles.notice}>{notice}</span> : null}
            </div>
            <div className={styles.pager} aria-label={labels.maintenance}>
              <span className={styles.rangeLabel}>
                {pagedMaintenance.start + (pagedMaintenance.items.length > 0 ? 1 : 0)}-{pagedMaintenance.end} / {maintenanceItems.length}
              </span>
              <VButton type="button" density="compact" variant="secondary" isDisabled={pagedMaintenance.page <= 1} onPress={() => setMaintenancePage((current) => current - 1)}>
                {labels.previous}
              </VButton>
              <strong>{pagedMaintenance.page}/{pagedMaintenance.pageCount}</strong>
              <VButton type="button" density="compact" variant="secondary" isDisabled={pagedMaintenance.page >= pagedMaintenance.pageCount} onPress={() => setMaintenancePage((current) => current + 1)}>
                {labels.next}
              </VButton>
            </div>
          </div>
          <VDenseTable
            ariaLabel={labels.maintenance}
            className={styles.statusTable}
            resizable
            rows={pagedMaintenance.items}
            getRowKey={(item) => item.id}
            onRowClick={(item) => onSelect(item.id)}
            getRowState={(item) => ({ selected: item.id === selectedId, tone: item.dirty ? "warning" : "neutral" })}
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
                render: (item) => (
                  <span onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                    <VCheckbox
                      aria-label={`${labels.cleanup} ${item.shortName || item.branch || item.id}`}
                      isSelected={cleanupSelected.includes(item.id)}
                      onChange={(next) => toggleSelected(item, next)}
                    />
                  </span>
                ),
              },
              {
                id: "branch",
                header: copy.branchColumn,
                width: 240,
                minWidth: 130,
                render: (item) => <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>,
              },
              {
                id: "state",
                header: copy.instanceState,
                width: 138,
                minWidth: 100,
                render: (item) => {
                  const state = instanceRuntimeState(item, pendingOperation);
                  return (
                    <VStatusChip tone={runtimeTone(state)}>
                      {instanceRuntimeStateLabel(state, zh)}
                    </VStatusChip>
                  );
                },
              },
              {
                id: "git",
                header: labels.git,
                width: 180,
                minWidth: 110,
                render: (item) => formatGitStatus(item, zh),
              },
              {
                id: "path",
                header: copy.instancePath,
                width: 320,
                minWidth: 160,
                fill: true,
                render: (item) => item.displayPath || item.path || "-",
              },
              {
                id: "actions",
                header: labels.actions,
                align: "right",
                width: 92,
                minWidth: 76,
                truncate: false,
                className: styles.actionCell,
                render: (item) => (
                  <span className={styles.actionButtons} onClick={(event) => event.stopPropagation()}>
                    <VButton type="button" variant="danger" density="compact" isDisabled={cleanupMutation.isPending} onPress={() => askCleanup([item.id])}>
                      {labels.cleanup}
                    </VButton>
                  </span>
                ),
              },
            ]}
          />
        </div>
      </details>

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
