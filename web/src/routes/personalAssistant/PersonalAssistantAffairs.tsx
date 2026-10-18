import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
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

export function PersonalAssistantAffairs({ agentId, headerAction }: {
  agentId: string;
  headerAction?: ReactNode;
}) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const [kindFilter, setKindFilter] = useState<PersonalAffairKind | "">("");
  const [statusFilter, setStatusFilter] = useState<PersonalAffairStatus | "">("");
  const [newKind, setNewKind] = useState<PersonalAffairKind>("todo");
  const [newTitle, setNewTitle] = useState("");
  const [newDue, setNewDue] = useState("");
  const [adding, setAdding] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actingKey, setActingKey] = useState<string | null>(null);
  const [dueEditor, setDueEditor] = useState<{ itemId: string; value: string } | null>(null);
  const affairs = useQuery({
    queryKey: queryKeys.personalAffairs(agentId, kindFilter, statusFilter),
    queryFn: ({ signal }) =>
      fetchPersonalAffairs(agentId, { kind: kindFilter, status: statusFilter, signal }),
    enabled: Boolean(agentId),
    retry: 1,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
  const data = affairs.data;

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["agents", agentId, "plugins", "personal-affairs"] });
  }

  async function addItem() {
    if (!agentId || adding) return;
    const title = newTitle.trim();
    if (!title) return;
    setAdding(true);
    setActionError(null);
    try {
      await addPersonalAffair(agentId, {
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
      setAdding(false);
    }
  }

  async function runItemAction(itemId: string, action: "complete" | "cancel" | "reopen") {
    if (actingKey) return;
    setActingKey(`${itemId}:${action}`);
    setActionError(null);
    try {
      if (action === "complete") await completePersonalAffair(agentId, itemId);
      else if (action === "cancel") await cancelPersonalAffair(agentId, itemId);
      else await reopenPersonalAffair(agentId, itemId);
      await refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : copy.saveFailed);
    } finally {
      setActingKey(null);
    }
  }

  async function saveDue(itemId: string, value: string) {
    if (actingKey) return;
    setActingKey(`${itemId}:due`);
    setActionError(null);
    try {
      await setPersonalAffairDue(agentId, itemId, toIsoInputValue(value));
      setDueEditor(null);
      await refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : copy.saveFailed);
    } finally {
      setActingKey(null);
    }
  }

  const items = data?.items ?? [];
  const filtered = Boolean(kindFilter || statusFilter);

  function actionButton(item: PersonalAffairItem, action: "complete" | "cancel" | "reopen", label: string) {
    const key = `${item.itemId}:${action}`;
    return <VButton variant={action === "complete" ? "secondary" : "ghost"} density="compact"
      isPending={actingKey === key} isDisabled={actingKey !== null && actingKey !== key}
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
          {items.map(item => <li key={item.itemId}>
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
                  <VButton variant="ghost" density="compact" isDisabled={actingKey !== null}
                    onClick={() => setDueEditor(dueEditor?.itemId === item.itemId
                      ? null : { itemId: item.itemId, value: toLocalInputValue(item.dueAt) })}>{copy.setDue}</VButton>
                </span> : <span className={styles.itemActions}>
                  {actionButton(item, "reopen", copy.reopenItem)}
                </span>}
              </div>
              {dueEditor?.itemId === item.itemId ? <div className={styles.dueEditor}>
                <label className={styles.addField}>
                  <span>{copy.addDue}</span>
                  <VInput type="datetime-local" aria-label={`${copy.setDue}: ${item.title}`}
                    value={dueEditor.value} isDisabled={actingKey !== null}
                    onChange={event => setDueEditor({ itemId: item.itemId, value: event.target.value })} />
                </label>
                <div className={styles.dueEditorRow}>
                  <span className={styles.dueEditorHint}>{copy.dueEditorHint}</span>
                  <span className={styles.itemActions}>
                    <VButton variant="primary" density="compact" isPending={actingKey === `${item.itemId}:due`}
                      isDisabled={actingKey !== null && actingKey !== `${item.itemId}:due`}
                      onClick={() => void saveDue(item.itemId, dueEditor.value)}>{copy.saveDue}</VButton>
                    <VButton variant="ghost" density="compact" isDisabled={actingKey !== null}
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
