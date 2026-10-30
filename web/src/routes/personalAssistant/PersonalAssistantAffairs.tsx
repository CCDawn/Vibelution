import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ClipboardList } from "lucide-react";

import {
  addPersonalAffair,
  cancelPersonalAffair,
  completePersonalAffair,
  fetchPersonalAffairs,
  reopenPersonalAffair,
  setPersonalAffairDue,
} from "../../api/personalAffairs";
import type {
  PersonalAffairDueState,
  PersonalAffairItem,
  PersonalAffairKind,
  PersonalAffairStatus,
} from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { VButton, VInput, VStateSurface, VStringSelect } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import styles from "./PersonalAssistantAffairs.styles";

/** Interface copy only; affair values arrive from the backend closed enums. */
const COPY = {
  zh: {
    title: "事务",
    subtitle: "查看和管理助理记下的待办、日程与目标。",
    counts: { open: "进行中", overdue: "已逾期", done: "已完成" },
    addTitle: "新增事务",
    addKind: "类型",
    addTitleField: "标题",
    addDue: "截止时间",
    add: "添加",
    kindFilter: "按类型",
    statusFilter: "按状态",
    all: "全部",
    kindLabels: { todo: "待办", schedule: "日程", goal: "目标" } as Record<PersonalAffairKind, string>,
    statusLabels: { open: "进行中", done: "已完成", cancelled: "已取消" } as Record<PersonalAffairStatus, string>,
    dueStateLabels: { overdue: "已逾期", today: "今天到期", upcoming: "即将到期", none: "无截止" } as Record<PersonalAffairDueState, string>,
    markDone: "完成",
    cancelItem: "取消",
    reopenItem: "重新打开",
    setDue: "设截止",
    saveDue: "保存",
    cancelEdit: "取消",
    dueEditorHint: "留空保存会清除截止时间。",
    empty: "还没有事务",
    emptyFiltered: "没有符合筛选的事务",
    loadFailed: "事务读取失败",
    retry: "重试",
    loading: "正在读取事务…",
    saveFailed: "操作失败，请稍后重试。",
    missingTarget: "提醒对应的事务已不存在，可能已被删除。",
  },
  en: {
    title: "Affairs",
    subtitle: "Track the todos, schedules and goals the assistant keeps for you.",
    counts: { open: "Open", overdue: "Overdue", done: "Done" },
    addTitle: "Add an affair",
    addKind: "Kind",
    addTitleField: "Title",
    addDue: "Due",
    add: "Add",
    kindFilter: "By kind",
    statusFilter: "By status",
    all: "All",
    kindLabels: { todo: "Todo", schedule: "Schedule", goal: "Goal" } as Record<PersonalAffairKind, string>,
    statusLabels: { open: "Open", done: "Done", cancelled: "Cancelled" } as Record<PersonalAffairStatus, string>,
    dueStateLabels: { overdue: "Overdue", today: "Due today", upcoming: "Upcoming", none: "No due" } as Record<PersonalAffairDueState, string>,
    markDone: "Complete",
    cancelItem: "Cancel",
    reopenItem: "Reopen",
    setDue: "Set due",
    saveDue: "Save",
    cancelEdit: "Cancel",
    dueEditorHint: "Saving an empty value clears the due time.",
    empty: "No affairs yet",
    emptyFiltered: "No affairs match the filters",
    loadFailed: "Failed to load affairs",
    retry: "Retry",
    loading: "Loading affairs…",
    saveFailed: "Failed to apply; please retry later.",
    missingTarget: "The affair for this reminder no longer exists; it may have been deleted.",
  },
} as const;

const KIND_OPTIONS = ["todo", "schedule", "goal"] as const;
const STATUS_OPTIONS = ["open", "done", "cancelled"] as const;

function formatDue(iso: string, lang: "zh" | "en"): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toLocalInputValue(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toIsoInputValue(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString();
}

export type PersonalAssistantAffairsTransport = { cacheKey: readonly unknown[] } & Pick<typeof import("../../api/personalAffairs"),
  "fetchPersonalAffairs" | "addPersonalAffair" | "completePersonalAffair" | "cancelPersonalAffair" | "reopenPersonalAffair" | "setPersonalAffairDue">;
const workbenchAffairs = { fetchPersonalAffairs, addPersonalAffair, completePersonalAffair, cancelPersonalAffair, reopenPersonalAffair, setPersonalAffairDue };

type PersonalAssistantAffairsProps = {
  agentId: string;
  transport?: PersonalAssistantAffairsTransport;
  headerAction?: ReactNode;
  focusItemId?: string;
  focusRequestKey?: string;
  focusRequestResult?: "found" | "missing";
  onFocusRequestHandled?: (requestKey: string, result: "found" | "missing") => void;
};

export function PersonalAssistantAffairs(props: PersonalAssistantAffairsProps) {
  // Agent identity owns drafts, errors and pending requests, including A → B → A.
  return <PersonalAssistantAffairsContent key={`${JSON.stringify(props.transport?.cacheKey ?? ["workbench"])}:${props.agentId}`} {...props} />;
}

function PersonalAssistantAffairsContent({ agentId, transport, headerAction, focusItemId, focusRequestKey,
  focusRequestResult, onFocusRequestHandled }: PersonalAssistantAffairsProps) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const api = transport ?? workbenchAffairs;
  const queryPrefix = transport ? [...transport.cacheKey, "personal-affairs", agentId] : ["agents", agentId, "plugins", "personal-affairs"];
  const [kindFilter, setKindFilter] = useState<PersonalAffairKind | "">("");
  const [statusFilter, setStatusFilter] = useState<PersonalAffairStatus | "">("");
  const itemRefs = useRef(new Map<string, HTMLLIElement>());
  const [pendingTarget, setPendingTarget] = useState<{
    itemId: string; requestKey?: string; agentId: string;
  } | null>(null);
  const [missingTarget, setMissingTarget] = useState(false);
  const [newKind, setNewKind] = useState<PersonalAffairKind>("todo");
  const [newTitle, setNewTitle] = useState("");
  const [newDue, setNewDue] = useState("");
  const [adding, setAdding] = useState(false);
  const addingRef = useRef(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const pendingItems = useRef(new Set<string>());
  const [itemActions, setItemActions] = useState<Record<string, string>>({});
  const [itemErrors, setItemErrors] = useState<Record<string, string>>({});
  const [dueEditor, setDueEditor] = useState<{ itemId: string; value: string } | null>(null);
  const affairs = useQuery({
    queryKey: transport ? [...queryPrefix, kindFilter, statusFilter] : queryKeys.personalAffairs(agentId, kindFilter, statusFilter),
    queryFn: ({ signal }) =>
      api.fetchPersonalAffairs(agentId, { kind: kindFilter, status: statusFilter, signal }),
    enabled: Boolean(agentId),
    retry: 1,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
  const data = affairs.data;

  useEffect(() => {
    // Route 保存已消费结果，tab/dialog 重挂载不重置筛选或重复定位。
    if (focusRequestResult) {
      setMissingTarget(focusRequestResult === "missing");
      return;
    }
    setMissingTarget(false);
    setPendingTarget(focusItemId ? { itemId: focusItemId, requestKey: focusRequestKey, agentId } : null);
    if (focusItemId) {
      setKindFilter("");
      setStatusFilter("");
    }
  }, [agentId, focusItemId, focusRequestKey, focusRequestResult]);

  useEffect(() => {
    // 等待无筛选的权威列表；定位完成后不因轮询或用户改筛选再抢焦点。
    if (focusRequestResult || !pendingTarget || pendingTarget.itemId !== focusItemId || pendingTarget.requestKey !== focusRequestKey
      || pendingTarget.agentId !== agentId || kindFilter || statusFilter || !affairs.isSuccess || affairs.isFetching) return;
    const item = itemRefs.current.get(pendingTarget.itemId);
    if (item) {
      item.focus({ preventScroll: true });
      item.scrollIntoView?.({ block: "center" });
    } else setMissingTarget(true);
    setPendingTarget(null);
    if (pendingTarget.requestKey) onFocusRequestHandled?.(pendingTarget.requestKey, item ? "found" : "missing");
  }, [pendingTarget, focusItemId, focusRequestKey, focusRequestResult, onFocusRequestHandled,
    agentId, kindFilter, statusFilter, affairs.isSuccess, affairs.isFetching, data]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: queryPrefix });
  }

  async function addItem() {
    if (!agentId || addingRef.current) return;
    const title = newTitle.trim();
    if (!title) return;
    addingRef.current = true;
    setAdding(true);
    setActionError(null);
    try {
      await api.addPersonalAffair(agentId, {
        kind: newKind,
        title,
        dueAt: toIsoInputValue(newDue),
      });
      setNewTitle("");
      setNewDue("");
      await refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : copy.saveFailed);
    } finally {
      addingRef.current = false;
      setAdding(false);
    }
  }

  async function runItemAction(itemId: string, action: "complete" | "cancel" | "reopen" | "due", value = "") {
    // The ref closes the same-event-loop gap before React renders disabled buttons.
    if (!agentId || pendingItems.current.has(itemId)) return;
    pendingItems.current.add(itemId);
    setItemActions(current => ({ ...current, [itemId]: action }));
    setItemErrors(current => ({ ...current, [itemId]: "" }));
    try {
      if (action === "complete") await api.completePersonalAffair(agentId, itemId);
      else if (action === "cancel") await api.cancelPersonalAffair(agentId, itemId);
      else if (action === "due") {
        await api.setPersonalAffairDue(agentId, itemId, toIsoInputValue(value));
        setDueEditor(current => current?.itemId === itemId ? null : current);
      } else await api.reopenPersonalAffair(agentId, itemId);
      await refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : copy.saveFailed;
      setItemErrors(current => ({ ...current, [itemId]: message }));
    } finally {
      pendingItems.current.delete(itemId);
      setItemActions(current => {
        const next = { ...current };
        delete next[itemId];
        return next;
      });
    }
  }

  const items = data?.items ?? [];
  const filtered = Boolean(kindFilter || statusFilter);

  function actionButton(item: PersonalAffairItem, action: "complete" | "cancel" | "reopen", label: string) {
    return <VButton variant={action === "complete" ? "secondary" : "ghost"} density="compact"
      isPending={itemActions[item.itemId] === action} isDisabled={Boolean(itemActions[item.itemId])}
      onClick={() => void runItemAction(item.itemId, action)}>{label}</VButton>;
  }

  return <section className={styles.root} aria-label={copy.title}>
    <div className={styles.pinned}>
      <header className={styles.header}>
        <div>
          <h2>{copy.title}</h2>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <div className={styles.headerActions}>{headerAction}</div>
      </header>
      {missingTarget ? <p className={styles.error} role="status">{copy.missingTarget}</p> : null}
    </div>
    <div className={styles.content}>
      {affairs.isError ? <VStateSurface density="compact" tone="error" title={copy.loadFailed}
        actions={<VButton variant="secondary" onClick={() => void affairs.refetch()}>{copy.retry}</VButton>}>
        {affairs.error instanceof Error ? affairs.error.message : ""}
      </VStateSurface> : null}
      {affairs.isPending ? <VStateSurface density="compact" tone="loading" busy skeletonLines title={copy.loading} /> : null}
      {actionError ? <p className={styles.error} role="alert">{actionError}</p> : null}
      {data ? <>
        <div className={styles.counts} aria-label={copy.title}>
          <span className={styles.countChip}>{copy.counts.open} {data.counts.open}</span>
          <span className={styles.countChipOverdue}>{copy.counts.overdue} {data.counts.overdue}</span>
          <span className={styles.countChip}>{copy.counts.done} {data.counts.done}</span>
        </div>
        <div className={styles.addForm}>
          <span className={styles.itemNote}>{copy.addTitle}</span>
          <div className={styles.addRow}>
            <label className={styles.addField}>
              <span>{copy.addTitleField}</span>
              <VInput aria-label={copy.addTitleField} value={newTitle} maxLength={160}
                isDisabled={adding} onChange={event => setNewTitle(event.target.value)} />
            </label>
            <VButton variant="primary" density="compact" isPending={adding}
              isDisabled={!newTitle.trim()} onClick={() => void addItem()}>{copy.add}</VButton>
          </div>
          <div className={styles.filters}>
            <label className={styles.addField}>
              <span>{copy.addKind}</span>
              <VStringSelect ariaLabel={copy.addKind} value={newKind} isDisabled={adding}
                onValueChange={value => setNewKind(value as PersonalAffairKind)}
                options={KIND_OPTIONS.map(value => ({ value, label: copy.kindLabels[value] }))} />
            </label>
            <label className={styles.addField}>
              <span>{copy.addDue}</span>
              <VInput type="datetime-local" aria-label={copy.addDue} value={newDue}
                isDisabled={adding} onChange={event => setNewDue(event.target.value)} />
            </label>
          </div>
        </div>
        <div className={styles.filters}>
          <VStringSelect ariaLabel={copy.kindFilter} value={kindFilter}
            onValueChange={value => setKindFilter(value as PersonalAffairKind | "")}
            options={[{ value: "", label: `${copy.kindFilter}: ${copy.all}` },
              ...KIND_OPTIONS.map(value => ({ value, label: copy.kindLabels[value] }))]} />
          <VStringSelect ariaLabel={copy.statusFilter} value={statusFilter}
            onValueChange={value => setStatusFilter(value as PersonalAffairStatus | "")}
            options={[{ value: "", label: `${copy.statusFilter}: ${copy.all}` },
              ...STATUS_OPTIONS.map(value => ({ value, label: copy.statusLabels[value] }))]} />
        </div>
        {items.length ? <ul className={styles.list}>
          {items.map(item => <li key={item.itemId} tabIndex={-1} className={styles.focusItem}
            ref={node => { if (node) itemRefs.current.set(item.itemId, node); else itemRefs.current.delete(item.itemId); }}>
            <div className={styles.item}>
              <div className={styles.itemHead}>
                <span className={styles.itemCopy}>
                  <strong>{item.title}</strong>
                  <span className={styles.itemMeta}>
                    <span className={item.dueState === "overdue" ? styles.badgeOverdue : styles.badge}>
                      {copy.kindLabels[item.kind]}
                    </span>
                    {item.status === "open" ? <span className={item.dueState === "overdue" ? styles.badgeOverdue : styles.badge}>
                      {copy.dueStateLabels[item.dueState]}
                    </span> : <span className={styles.badge}>{copy.statusLabels[item.status]}</span>}
                    {item.dueAt ? <span className={styles.itemNote}>{formatDue(item.dueAt, lang)}</span> : null}
                  </span>
                  {item.note ? <span className={styles.itemNote}>{item.note}</span> : null}
                </span>
                {item.status === "open" ? <span className={styles.itemActions}>
                  {actionButton(item, "complete", copy.markDone)}
                  {actionButton(item, "cancel", copy.cancelItem)}
                  <VButton variant="ghost" density="compact" isDisabled={Boolean(itemActions[item.itemId])}
                    onClick={() => {
                      if (pendingItems.current.has(item.itemId)) return;
                      setDueEditor(current => current?.itemId === item.itemId
                        ? null : { itemId: item.itemId, value: toLocalInputValue(item.dueAt) });
                    }}>{copy.setDue}</VButton>
                </span> : <span className={styles.itemActions}>
                  {actionButton(item, "reopen", copy.reopenItem)}
                </span>}
              </div>
              {itemErrors[item.itemId] ? <p className={styles.error} role="alert">{itemErrors[item.itemId]}</p> : null}
              {dueEditor?.itemId === item.itemId ? <div className={styles.dueEditor}>
                <label className={styles.addField}>
                  <span>{copy.addDue}</span>
                  <VInput type="datetime-local" aria-label={`${copy.setDue}: ${item.title}`}
                    value={dueEditor.value} isDisabled={Boolean(itemActions[item.itemId])}
                    onChange={event => setDueEditor({ itemId: item.itemId, value: event.target.value })} />
                </label>
                <div className={styles.dueEditorRow}>
                  <span className={styles.dueEditorHint}>{copy.dueEditorHint}</span>
                  <span className={styles.itemActions}>
                    <VButton variant="primary" density="compact" isPending={itemActions[item.itemId] === "due"}
                      isDisabled={Boolean(itemActions[item.itemId])}
                      onClick={() => void runItemAction(item.itemId, "due", dueEditor.value)}>{copy.saveDue}</VButton>
                    <VButton variant="ghost" density="compact" isDisabled={Boolean(itemActions[item.itemId])}
                      onClick={() => setDueEditor(null)}>{copy.cancelEdit}</VButton>
                  </span>
                </div>
              </div> : null}
            </div>
          </li>)}
        </ul> : <div className={styles.empty}>
          <ClipboardList size={20} />
          <strong>{filtered ? copy.emptyFiltered : copy.empty}</strong>
        </div>}
      </> : null}
    </div>
  </section>;
}
