import {
  Bot,
  Check,
  CornerUpLeft,
  ChevronDown,
  ChevronRight,
  FolderPlus,
  LoaderCircle,
  Pencil,
  Plus,
  SquareTerminal,
  Trash2,
  X,
} from "lucide-react";
import type { DragEvent, KeyboardEvent, MouseEvent as ReactMouseEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AgentInstance, SessionReferenceAttachment, SessionSummary, Team } from "../api/types";
import type { AgentSessionTabGroupState } from "./agentSessionTabGroups";
import { VButton, VDropdownMenu, VHoverCard, VIconButton, VNativeInput, VPopover } from "../components/vui";
import type { VDropdownMenuItem } from "../components/vui";
import type { TranslationKey } from "../i18n/dictionary";
import { sessionAgentDisplayInfo } from "./agentDisplay";

/** Dedicated drag type so tab reordering never collides with reference dragging. */
const SESSION_TAB_ORDER_MIME = "application/x-vibelution-session-order";
import {
  applyAgentSessionTabOrder,
  persistAgentSessionTabOrder,
  reorderSessionIds,
} from "./agentSessionTabOrder";
import {
  UNGROUPED_SECTION_ID,
  assignSessionToTabGroup,
  createAgentSessionTabGroup,
  defaultAgentSessionTabGroupName,
  deleteAgentSessionTabGroup,
  readAgentSessionTabGroupState,
  renameAgentSessionTabGroup,
  resolveSessionTabGroupSections,
  sessionTabGroupIdFor,
  setAgentSessionTabGroupCollapsed,
  writeAgentSessionTabGroupState,
  TAB_GROUP_COLORS,
  mergeSessionsIntoTabGroup,
  sessionTabGroupColorFor,
  setAgentSessionTabGroupColor,
  type AgentSessionTabGroupColor,
  type AgentSessionTabGroupSection,
} from "./agentSessionTabGroups";
import {
  resolveSessionActivityTone,
  sessionActivityLabel,
  type SessionActivityTone,
} from "./sessionActivityIndicator";
import styles from "./AgentSessionTabStrip.styles";

/** Palette accent per group colour; the swatch colours live in the styles module. */
/** Colour names are localised palette labels; the stored value stays a token. */
const GROUP_COLOR_LABELS: Record<AgentSessionTabGroupColor, { zh: string; en: string }> = {
  gray: { zh: "灰色", en: "Gray" },
  blue: { zh: "蓝色", en: "Blue" },
  green: { zh: "绿色", en: "Green" },
  amber: { zh: "琥珀", en: "Amber" },
  violet: { zh: "紫色", en: "Violet" },
  rose: { zh: "玫红", en: "Rose" },
};

const GROUP_SWATCH_CLASS: Record<AgentSessionTabGroupColor, string> = {
  gray: styles.agentSessionTabGroupSwatchGray,
  blue: styles.agentSessionTabGroupSwatchBlue,
  green: styles.agentSessionTabGroupSwatchGreen,
  amber: styles.agentSessionTabGroupSwatchAmber,
  violet: styles.agentSessionTabGroupSwatchViolet,
  rose: styles.agentSessionTabGroupSwatchRose,
};

/** Group colour dot: the chip's only colour signal, so one chip keeps one accent. */
const GROUP_TINT_CLASS: Record<AgentSessionTabGroupColor, string> = {
  gray: styles.agentSessionTabGroupTintGray,
  blue: styles.agentSessionTabGroupTintBlue,
  green: styles.agentSessionTabGroupTintGreen,
  amber: styles.agentSessionTabGroupTintAmber,
  violet: styles.agentSessionTabGroupTintViolet,
  rose: styles.agentSessionTabGroupTintRose,
};

const GROUP_DOT_CLASS: Record<AgentSessionTabGroupColor, string> = {
  gray: styles.agentSessionTabGroupDotGray,
  blue: styles.agentSessionTabGroupDotBlue,
  green: styles.agentSessionTabGroupDotGreen,
  amber: styles.agentSessionTabGroupDotAmber,
  violet: styles.agentSessionTabGroupDotViolet,
  rose: styles.agentSessionTabGroupDotRose,
};
import "./AgentSessionTabStrip.armed.css";
import "./AgentSessionTabStrip.groups.css";
import { sessionBlocksMutation } from "./sessionActivityState";
import {
  PANE_DOCK_MIME,
  readPaneDock,
  writePaneDock,
  type PaneDockPayload,
  type SessionBarDockChip,
} from "./chat/chatPaneDock";
import { SessionTeamBindingTag } from "./chat/SessionTeamBindingTag";

/** How long the armed (two-stage confirm) close control waits before disarming itself. */
const CLOSE_CONFIRM_ARM_TIMEOUT_MS = 3000;

/**
 * After one confirmed close, × clicks execute immediately (no arming) for this
 * window — rapid multi-tab closing stays single-click per tab, Chrome-style.
 * Escape ends the window early; the window refreshes on every burst close.
 */
const RAPID_CLOSE_BURST_WINDOW_MS = 2000;

/** Options accepted by the delete callback; `confirmed` marks the second click of the inline confirm. */
export type AgentSessionTabDeleteOptions = {
  confirmed?: boolean;
};

export type CliAgentRunTab = {
  id: string;
  title: string;
  summary: string;
  status: string;
  agentType: string;
  mode: string;
};

/**
 * Tab activity indicators (not selection):
 * - green spinner  running  = 会话进行中
 * - yellow spinner approval = 需要审批
 * - red light      error    = 出错
 * - blue light     completed = 有新消息（未读，不表示执行成功）
 * - none           idle / already read
 * Selection is a separate border/ring on the active tab.
 */
export type AgentSessionStatusTone = SessionActivityTone;

/** Header aggregate: approval outranks running, then error, unread, idle. */


const GROUP_TONE_PRIORITY: Record<AgentSessionStatusTone, number> = {
  approval: 6,
  running: 5,
  stopping: 4,
  error: 3,
  completed: 2,
  paused: 1,
  none: 0,
};

export function agentSessionStatusTone(
  status: string,
  options?: {
    needsApproval?: boolean;
    isRuntimeRunning?: boolean;
    isOptimisticRunning?: boolean;
    session?: Pick<
      SessionSummary,
      | "id"
      | "childStatus"
      | "currentPhase"
      | "status"
      | "lastTurnStatus"
      | "terminalReason"
      | "sessionKind"
      | "taskSummary"
      | "updatedAt"
      | "lastActive"
      | "agentInboxPendingCount"
    >;
    isActive?: boolean;
  },
): AgentSessionStatusTone {
  if (options?.session) {
    return resolveSessionActivityTone(
      options.session,
      {
        needsApproval: options.needsApproval,
        isRuntimeRunning: options.isRuntimeRunning,
        isOptimisticRunning: options.isOptimisticRunning,
        isActive: options.isActive,
      },
    );
  }
  return resolveSessionActivityTone(
    { status },
    {
      needsApproval: options?.needsApproval,
      isRuntimeRunning: options?.isRuntimeRunning,
      isOptimisticRunning: options?.isOptimisticRunning,
      isActive: options?.isActive,
    },
  );
}

function agentSessionStatusIndicatorClassName(tone: AgentSessionStatusTone) {
  return [
    styles.agentSessionTabStatusIndicator,
    tone === "running" ? styles.agentSessionTabStatusRunning : "",
    tone === "error" ? styles.agentSessionTabStatusError : "",
    tone === "approval" ? styles.agentSessionTabStatusApproval : "",
    tone === "completed" ? styles.agentSessionTabStatusCompleted : "",
  ].filter(Boolean).join(" ");
}

/** Fixed-width status cell: always rendered so tab width/close alignment stay stable. */
function renderAgentSessionStatusSlot(tone: AgentSessionStatusTone) {
  return (
    <span className={styles.agentSessionTabStatusSlot} aria-hidden="true" data-session-tab-status-slot>
      {tone === "none" ? null : (
        <span className={styles.agentSessionTabStatus}>
          <span className={agentSessionStatusIndicatorClassName(tone)}>
            {tone === "running" || tone === "approval" ? (
              <LoaderCircle size={11} aria-hidden="true" className={styles.agentSessionTabStatusSpinner} />
            ) : null}
          </span>
        </span>
      )}
    </span>
  );
}

/** Group header status: a bare dot cannot say how many sessions are waiting. */
function renderAgentSessionGroupStatus(
  counts: Record<AgentSessionStatusTone, number>,
  lang: "zh" | "en",
) {
  const focus = (["approval", "running", "error", "completed"] as const).find(
    (tone) => counts[tone] > 0,
  );
  if (!focus) {
    return (
      <span
        className={styles.agentSessionTabStatusSlot}
        aria-hidden="true"
        data-session-tab-status-slot
      />
    );
  }
  const badgeClassName = [
    styles.agentSessionTabGroupStatusBadge,
    focus === "approval" ? styles.agentSessionTabGroupStatusBadgeApproval : "",
    focus === "running" ? styles.agentSessionTabGroupStatusBadgeRunning : "",
    focus === "error" ? styles.agentSessionTabGroupStatusBadgeError : "",
    focus === "completed" ? styles.agentSessionTabGroupStatusBadgeCompleted : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <span
      className={styles.agentSessionTabGroupStatusSlot}
      title={sessionActivityLabel(focus, lang)}
      data-session-tab-group-status={focus}
      data-session-tab-group-status-count={counts[focus]}
    >
      <span className={badgeClassName}>{counts[focus]}</span>
    </span>
  );
}

export function agentSessionStatusShortLabel(tone: AgentSessionStatusTone, lang: "zh" | "en") {
  return sessionActivityLabel(tone, lang);
}

export type AgentSessionTabStripProps = {
  activeSessionId: string | null;
  activeCliAgentRunId?: string;
  agentsById: Map<string, AgentInstance>;
  buildSessionReferencePayload: (
    session: SessionSummary,
    displayName: string,
    summary: string,
  ) => SessionReferenceAttachment;
  contextMenuSessionId: string;
  editingSessionId: string | null;
  editingSessionTitle: string;
  lang: "zh" | "en";
  renamePending: boolean;
  renameSessionId: string;
  resolveModelLabel: (modelId: string) => string | undefined;
  cliAgentRuns?: CliAgentRunTab[];
  createPending?: boolean;
  createDisabled?: boolean;
  /** When set, only that session's close control is pending (not a global lock). */
  deletePendingSessionId?: string;
  /** @deprecated use deletePendingSessionId — global true freezes every tab close. */
  deletePending?: boolean;
  sessions: SessionSummary[];
  /** Active team catalog for membership-based「团队」binding tags. */
  teams?: Team[];
  /** Session ids with an active runtime chat_turn (green spinner). */
  runtimeRunningSessionIds?: readonly string[];
  /** Session ids with a fresh local optimistic turn (spinner before the
   *  session summary itself reaches ``running``). */
  optimisticRunningSessionIds?: readonly string[];
  /** Session ids waiting on tool/permission approval (yellow spinner). */
  sessionIdsNeedingApproval?: readonly string[];
  statusLabel: (status: string) => string;
  t: (key: TranslationKey) => string;
  workspaceActiveTab: string;
  onCancelRename: () => void;
  onContextMenu: (event: ReactMouseEvent<HTMLElement>, session: SessionSummary) => void;
  onDragReference: (event: DragEvent<HTMLElement>, reference: SessionReferenceAttachment) => void;
  onOpenDirectSession: (sessionId: string) => void;
  onPrefetchDirectSession?: (sessionId: string) => void;
  onOpenCliAgentRun?: (runId: string) => void;
  onCloseCliAgentRun?: (runId: string) => void;
  onCreateSession: () => void;
  /**
   * First × click arms the inline confirm; the second click on the armed control
   * passes `{ confirmed: true }` so the route deletes without a dialog.
   */
  onDeleteSession: (session: SessionSummary, options?: AgentSessionTabDeleteOptions) => void;
  onRenameTitleChange: (title: string) => void;
  onSetActiveTab: (sessionId: string, tab: "agent") => void;
  onSubmitRename: (session: SessionSummary, options?: { reason?: "blur" | "explicit" }) => void;
  paneDockChips?: SessionBarDockChip[];
  onPaneDockChipSelect?: (chip: SessionBarDockChip) => void;
  onPaneDockChipClose?: (chip: SessionBarDockChip) => void;
  onPaneDockDrop?: (payload: PaneDockPayload) => void;
  /** Right-rail pages drawn in the same session row. Drag still uses the pane-dock payload. */
  railRowTabs?: SessionBarRailTab[];
  onRailRowTabSelect?: (tabId: string) => void;
  onRailRowTabClose?: (tabId: string) => void;
};

export type SessionBarRailTab = {
  id: string;
  title: string;
  active: boolean;
};

function agentSessionTabElementId(kind: "session" | "cli", id: string) {
  return `agent-session-tab-${kind}-${encodeURIComponent(id)}`;
}

export function AgentSessionTabStrip({
  activeSessionId,
  activeCliAgentRunId = "",
  agentsById,
  buildSessionReferencePayload,
  contextMenuSessionId,
  editingSessionId,
  editingSessionTitle,
  lang,
  renamePending,
  renameSessionId,
  resolveModelLabel,
  cliAgentRuns = [],
  createPending = false,
  createDisabled = false,
  deletePendingSessionId = "",
  deletePending = false,
  sessions,
  teams = [],
  runtimeRunningSessionIds = [],
  optimisticRunningSessionIds = [],
  sessionIdsNeedingApproval = [],
  statusLabel: _statusLabel,
  t,
  workspaceActiveTab,
  onCancelRename,
  onContextMenu,
  onDragReference,
  onOpenDirectSession,
  onPrefetchDirectSession,
  onOpenCliAgentRun,
  onCloseCliAgentRun,
  onCreateSession,
  onDeleteSession,
  onRenameTitleChange,
  onSetActiveTab,
  onSubmitRename,
  paneDockChips = [],
  onPaneDockChipSelect,
  onPaneDockChipClose,
  onPaneDockDrop,
  railRowTabs = [],
  onRailRowTabSelect,
  onRailRowTabClose,
}: AgentSessionTabStripProps) {
  // The strip scrolls horizontally, so every session of the selected agent
  // stays reachable. Truncating to a recent window silently hid older rows
  // (they vanished from the strip with no overflow entry); the active / edit
  // ids no longer need pinning because nothing is dropped anymore.
  const agentTabScopeId = String(sessions[0]?.agentId || "").trim();
  // Manual drag order wins over server order. localStorage is not reactive, so a
  // tick forces a recompute after each drop.
  const [manualOrderTick, setManualOrderTick] = useState(0);
  const [dragOrderSessionId, setDragOrderSessionId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{ sessionId: string; position: "before" | "after" } | null>(null);
  const visibleSessions = (() => {
    void manualOrderTick;
    return applyAgentSessionTabOrder(sessions, agentTabScopeId);
  })();
  // Read the stored bucket once per Agent scope; every mutation writes back
  // through setGroupState, so renders no longer re-parse localStorage.
  const [groupState, setGroupState] = useState<AgentSessionTabGroupState>(() =>
    readAgentSessionTabGroupState(agentTabScopeId),
  );
  const [groupDropTarget, setGroupDropTarget] = useState<string | null>(null);
  const [mergeTargetSessionId, setMergeTargetSessionId] = useState<string | null>(null);
  const [renamingGroupId, setRenamingGroupId] = useState<string | null>(null);
  const [groupNameDraft, setGroupNameDraft] = useState("");
  // Group mutations write localStorage directly; this tick forces the next
  // render to re-read it, mirroring manualOrderTick above.
  const [, setGroupTick] = useState(0);
  const applyGroupMutation = useCallback(
    (mutate: (state: AgentSessionTabGroupState) => AgentSessionTabGroupState) => {
      setGroupState((current) => {
        const next = mutate(current);
        if (next === current) {
          return current;
        }
        writeAgentSessionTabGroupState(agentTabScopeId, next);
        return next;
      });
    },
    [agentTabScopeId],
  );
  // Switching Agent means a different stored bucket: re-read it.
  useEffect(() => {
    setGroupState(readAgentSessionTabGroupState(agentTabScopeId));
  }, [agentTabScopeId]);
  const groupSections = (() => {
    const resolved = resolveSessionTabGroupSections(visibleSessions, groupState, {
      ungroupedName: lang === "zh" ? "未分组" : "Ungrouped",
    });
    if (!renamingGroupId || resolved.some((section) => section.groupId === renamingGroupId)) {
      return resolved;
    }
    // A freshly created group has no members yet; keep its header visible so the
    // inline rename field has somewhere to live.
    const pending = groupState.groups.find((group) => group.id === renamingGroupId);
    if (!pending) {
      return resolved;
    }
    const pendingSection: AgentSessionTabGroupSection = {
      groupId: pending.id,
      name: pending.name,
      collapsed: false,
      ungrouped: false,
      sessions: [],
    };
    return [...resolved, pendingSection];
  })();
  const commitGroupDrop = useCallback(
    (sectionGroupId: string) => {
      const sessionId = dragOrderSessionId;
      setGroupDropTarget(null);
      setDropTarget(null);
      if (!sessionId) {
        return;
      }
      const targetGroupId = sectionGroupId === UNGROUPED_SECTION_ID ? null : sectionGroupId;
      applyGroupMutation((state) => assignSessionToTabGroup(state, sessionId, targetGroupId));
      setDragOrderSessionId(null);
    },
    [applyGroupMutation, dragOrderSessionId],
  );
  /**
   * Dropping on the middle band of another tab merges the two sessions into a
   * brand-new group. Folder semantics forbid extending the target's group, so a
   * new group is always created and can be renamed from its header.
   */
  const commitMergeDrop = useCallback(
    (targetSessionId: string) => {
      const sourceSessionId = dragOrderSessionId;
      setMergeTargetSessionId(null);
      setGroupDropTarget(null);
      setDropTarget(null);
      setDragOrderSessionId(null);
      if (!sourceSessionId || sourceSessionId === targetSessionId) {
        return;
      }
      applyGroupMutation((state) =>
        mergeSessionsIntoTabGroup(
          state,
          [sourceSessionId, targetSessionId],
          defaultAgentSessionTabGroupName(state, lang === "zh" ? "分组" : "Group"),
        ).state,
      );
    },
    [applyGroupMutation, dragOrderSessionId, lang],
  );
  const startGroupCreate = useCallback(() => {
    const current = readAgentSessionTabGroupState(agentTabScopeId);
    const name = defaultAgentSessionTabGroupName(current, lang === "zh" ? "分组" : "Group");
    const created = createAgentSessionTabGroup(current, name);
    writeAgentSessionTabGroupState(agentTabScopeId, created.state);
    setGroupTick((tick) => tick + 1);
    setRenamingGroupId(created.groupId);
    setGroupNameDraft(name);
  }, [agentTabScopeId, lang]);
  const startGroupRename = useCallback((section: AgentSessionTabGroupSection) => {
    setRenamingGroupId(section.groupId);
    setGroupNameDraft(section.name);
  }, []);
  const commitGroupRename = useCallback(
    (groupId: string) => {
      const next = groupNameDraft.trim();
      setRenamingGroupId(null);
      setGroupNameDraft("");
      if (!next) {
        return;
      }
      applyGroupMutation((state) => renameAgentSessionTabGroup(state, groupId, next));
    },
    [applyGroupMutation, groupNameDraft],
  );
  const renderSessionTab = (session: SessionSummary, sectionGroupId: string) => {
    const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
    const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
    const sessionStatus = session.status;
    const needsApproval = approvalSessionIds.has(session.id);
    const isRuntimeRunning = runtimeSessionIds.has(session.id);
    const tabActive = activeSessionId === session.id && workspaceActiveTab === "agent" && !activeCliAgentRunId;
    const statusTone = agentSessionStatusTone(String(sessionStatus || ""), {
      needsApproval,
      isRuntimeRunning,
      isOptimisticRunning: optimisticSessionIds.has(session.id),
      session,
      // Blue/unread clears for the open conversation, even if a file tab is in front.
      isActive: activeSessionId === session.id,
    });
    const statusShortLabel = agentSessionStatusShortLabel(statusTone, lang);
    const sessionTitle =
      session.title
      || sessionDisplay.name
      || t("agentSession");
    const sessionSummary =
      session.taskSummary
      || session.resultCard?.summary
      || sessionDisplay.modelLabel
      || "";
    const sessionHoverTitle = [sessionTitle, statusShortLabel, sessionSummary, sessionDisplay.modelLabel]
      .filter(Boolean)
      .join(" · ");
    const tabContextTarget = contextMenuSessionId === session.id;
    const tabEditing = editingSessionId === session.id;
    const keyboardIndex = keyboardTabs.findIndex((tab) => tab.kind === "session" && tab.id === session.id);
    const sessionDeletePending = Boolean(
      deletePending
      || (deletePendingSessionId && deletePendingSessionId === session.id),
    );
    const deleteDisabled = sessionBlocksMutation(session) || sessionDeletePending;
    const tabCloseArmed = !deleteDisabled && armedCloseSessionId === session.id;
    const tabCloseTitle = deleteDisabled
      ? t("deleteSessionBusy")
      : tabCloseArmed
        ? t("deleteSessionConfirmArmed")
        : t("deleteSession");
    const tabClassName = [
      styles.agentSessionTab,
      styles.agentSessionTabRoot,
      tabActive ? styles.agentSessionTabActive : "",
      tabContextTarget && !tabActive ? styles.agentSessionTabContextTarget : "",
      tabEditing ? styles.agentSessionTabEditing : "",
      dragOrderSessionId === session.id ? styles.agentSessionTabDragging : "",
      dropTarget && dropTarget.sessionId === session.id
        ? dropTarget.position === "before"
          ? styles.agentSessionTabDropBefore
          : styles.agentSessionTabDropAfter
        : "",
    ].filter(Boolean).join(" ");
    const tabMainActionClassName = [
      styles.agentSessionTabMainAction,
      tabActive ? styles.agentSessionTabMainActionActive : "",
      tabContextTarget && !tabActive ? styles.agentSessionTabMainActionContextTarget : "",
    ].filter(Boolean).join(" ");
    if (tabEditing) {
      const sessionRenamePending = renamePending && renameSessionId === session.id;
      return (
        <div
          key={session.id}
          className={tabClassName}
          role="presentation"
          data-selected={tabActive ? "true" : undefined}
          data-agent-session-tab-container
          onContextMenu={(event) => onContextMenu(event, session)}
        >
          <span className={styles.agentSessionTabIcon} aria-hidden="true">
            <Bot size={14} />
          </span>
          <VNativeInput
            className={styles.agentSessionTabTitleInput}
            value={editingSessionTitle}
            maxLength={120}
            autoFocus
            placeholder={lang === "zh" ? "会话名称" : "Session name"}
            onChange={(event) => onRenameTitleChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                onSubmitRename(session, { reason: "explicit" });
              }
              if (event.key === "Escape") {
                event.preventDefault();
                onCancelRename();
              }
            }}
            onBlur={(event) => {
              const nextFocus = event.relatedTarget;
              if (nextFocus instanceof Node && event.currentTarget.closest("[data-agent-session-tab-container]")?.contains(nextFocus)) {
                return;
              }
              onSubmitRename(session, { reason: "blur" });
            }}
            aria-label={t("renameSession")}
          />
          <span className={styles.agentSessionTabEditActions}>
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.agentSessionTabEditButton}
              onPress={() => onSubmitRename(session, { reason: "explicit" })}
              isDisabled={sessionRenamePending}
              title={t("saveSessionName")}
              label={`${t("saveSessionName")} ${sessionTitle}`}
              icon={<Check size={13} />}
            />
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.agentSessionTabEditButton}
              onPress={onCancelRename}
              isDisabled={sessionRenamePending}
              title={t("cancelRenameSession")}
              label={t("cancelRenameSession")}
              icon={<X size={13} />}
            />
          </span>
        </div>
      );
    }
    const dragReferenceProps = {
      draggable: true,
      onDragStart: (event: DragEvent<HTMLDivElement>) => {
        onDragReference(
          event,
          buildSessionReferencePayload(session, sessionDisplay.name, sessionSummary),
        );
        writePaneDock(event.dataTransfer, {
          v: 1,
          source: "session",
          sessionId: session.id,
          title: sessionTitle,
        });
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = "copyMove";
        }
      },
    };
    return (
      <div
        key={session.id}
        className={`${tabClassName} ${styles.agentSessionTabClosable}`}
        role="presentation"
        data-selected={tabActive ? "true" : undefined}
        data-agent-session-tab-container
        data-session-tab-merge-target={mergeTargetSessionId === session.id ? "true" : undefined}
        {...dragReferenceProps}
        onDragStart={(event) => {
          // The whole tab is the drag handle: keep the reference payload and add the
          // reorder/group payload, so the drop target decides between reference,
          // reorder and regrouping.
          dragReferenceProps.onDragStart(event);
          setDragOrderSessionId(session.id);
          event.dataTransfer.setData(SESSION_TAB_ORDER_MIME, session.id);
        }}
        onDragEnd={() => {
          setDragOrderSessionId(null);
          setDropTarget(null);
        }}
        onDragOver={(event) => {
          if (!dragOrderSessionId) {
            return;
          }
          event.preventDefault();
          event.stopPropagation();
          event.dataTransfer.dropEffect = "move";
          if (sessionTabGroupIdFor(groupState, dragOrderSessionId) !== sectionGroupId) {
            // Cross-group drag: highlight the section instead of showing an
            // insertion caret, because the drop moves the session, not the order.
            setDropTarget(null);
            setGroupDropTarget(sectionGroupId);
            return;
          }
          const bounds = event.currentTarget.getBoundingClientRect();
          const ratio = (event.clientX - bounds.left) / Math.max(1, bounds.width);
          if (ratio > 1 / 3 && ratio < 2 / 3) {
            // Middle band means merge, not reorder.
            setDropTarget(null);
            setMergeTargetSessionId(session.id);
            return;
          }
          setMergeTargetSessionId(null);
          const position = event.clientX < bounds.left + bounds.width / 2 ? "before" : "after";
          setDropTarget((current) => (
            current && current.sessionId === session.id && current.position === position
              ? current
              : { sessionId: session.id, position }
          ));
        }}
        onDrop={(event) => {
          if (!dragOrderSessionId) {
            return;
          }
          event.preventDefault();
          event.stopPropagation();
          if (sessionTabGroupIdFor(groupState, dragOrderSessionId) !== sectionGroupId) {
            commitGroupDrop(sectionGroupId);
            return;
          }
          const bounds = event.currentTarget.getBoundingClientRect();
          const ratio = (event.clientX - bounds.left) / Math.max(1, bounds.width);
          if (ratio > 1 / 3 && ratio < 2 / 3) {
            commitMergeDrop(session.id);
            return;
          }
          const position = event.clientX < bounds.left + bounds.width / 2 ? "before" : "after";
          commitTabOrderDrop(session.id, position);
          setDropTarget(null);
        }}
        onDragLeave={() => {
          setDropTarget((current) => (current?.sessionId === session.id ? null : current));
        }}
        onContextMenu={(event) => onContextMenu(event, session)}
      >
        <VButton
          type="button"
          contentLayout="plain"
          className={tabMainActionClassName}
          id={agentSessionTabElementId("session", session.id)}
          role="tab"
          aria-selected={tabActive}
          aria-current={tabActive ? "true" : undefined}
          tabIndex={keyboardIndex === activeKeyboardTabIndex ? 0 : -1}
          onKeyDown={(event) => handleTabKeyDown(event, keyboardIndex)}
          data-session-tab-active={tabActive ? "true" : "false"}
          onPointerEnter={() => onPrefetchDirectSession?.(session.id)}
          onFocus={() => onPrefetchDirectSession?.(session.id)}
          onPress={() => {
            if (activeSessionId === session.id) {
              onSetActiveTab(session.id, "agent");
              return;
            }
            onOpenDirectSession(session.id);
          }}
          title={sessionHoverTitle}
          aria-label={
            tabActive
              ? (statusShortLabel
                ? `${lang === "zh" ? "当前会话" : "Current session"}: ${sessionTitle} · ${statusShortLabel}`
                : `${lang === "zh" ? "当前会话" : "Current session"}: ${sessionTitle}`)
              : (statusShortLabel ? `${sessionTitle} · ${statusShortLabel}` : sessionTitle)
          }
        >
          <span
            className={[
              styles.agentSessionTabIcon,
              tabActive ? styles.agentSessionTabIconActive : "",
            ].filter(Boolean).join(" ")}
            aria-hidden="true"
          >
            <Bot size={14} />
          </span>
          <span className={styles.agentSessionTabTitleBlock}>
            <span
              className={[
                styles.agentSessionTabTitle,
                tabActive ? styles.agentSessionTabTitleActive : "",
              ].filter(Boolean).join(" ")}
            >{sessionTitle}</span>
          </span>
          {renderAgentSessionStatusSlot(statusTone)}
        </VButton>
        <SessionTeamBindingTag session={session} lang={lang} teams={teams} />
        <VIconButton
          type="button"
          variant="ghost"
          className={[
            styles.agentSessionTabCloseButton,
            tabCloseArmed ? styles.agentSessionTabCloseButtonArmed : "",
          ].filter(Boolean).join(" ")}
          data-session-tab-close-armed={tabCloseArmed ? "true" : undefined}
          onClick={(event) => {
            event.stopPropagation();
            // Rapid-close burst: once one tab close was confirmed, an
            // immediate × click on any tab is a deliberate close.
            const inRapidCloseBurst = !tabCloseArmed && Date.now() < rapidCloseUntilRef.current;
            if (tabCloseArmed || inRapidCloseBurst) {
              disarmCloseConfirm();
              rapidCloseUntilRef.current = Date.now() + RAPID_CLOSE_BURST_WINDOW_MS;
              onDeleteSession(session, { confirmed: true });
              return;
            }
            setArmedCloseSessionId(session.id);
          }}
          isDisabled={deleteDisabled}
          title={tabCloseTitle}
          label={`${tabCloseTitle} ${sessionTitle}`}
          icon={<X size={13} />}
        />
      </div>
    );
  };

  const groupSessionTone = (session: SessionSummary): AgentSessionStatusTone =>
    agentSessionStatusTone(String(session.status || ""), {
      needsApproval: approvalSessionIds.has(session.id),
      isRuntimeRunning: runtimeSessionIds.has(session.id),
      isOptimisticRunning: optimisticSessionIds.has(session.id),
      session,
      isActive: activeSessionId === session.id,
    });

  const groupToneCounts = (section: AgentSessionTabGroupSection) => {
    const counts: Record<AgentSessionStatusTone, number> = {
      approval: 0,
      running: 0,
      stopping: 0,
      paused: 0,
      error: 0,
      completed: 0,
      none: 0,
    };
    for (const session of section.sessions) {
      counts[groupSessionTone(session)] += 1;
    }
    return counts;
  };

  const groupAggregateTone = (section: AgentSessionTabGroupSection): AgentSessionStatusTone =>
    section.sessions.reduce<AgentSessionStatusTone>(
      (worst, session) => {
        const tone = groupSessionTone(session);
        return GROUP_TONE_PRIORITY[tone] > GROUP_TONE_PRIORITY[worst] ? tone : worst;
      },
      "none",
    );

  /** Vertical group panel: mouse-first, one click switches the session and closes the panel. */
  const renderGroupPopoverList = (section: AgentSessionTabGroupSection) => {
    const activeColor = sessionTabGroupColorFor(groupState, section.groupId);
    const groupTint = activeColor ? GROUP_TINT_CLASS[activeColor] : "";
    if (!section.sessions.length) {
      return (
        <p className={styles.agentSessionTabGroupPanelEmpty}>
          {lang === "zh" ? "这个分组还没有会话" : "No sessions in this group"}
        </p>
      );
    }
    return (
      <ul className={[styles.agentSessionTabGroupPanelList, groupTint].filter(Boolean).join(" ")}>
        {section.sessions.map((session) => {
          const sessionActive = activeSessionId === session.id;
          return (
            <li
              key={session.id}
              className={styles.agentSessionTabGroupPanelRow}
              draggable
              onDragStart={(event) => {
                // A panel member is the only drag source that can leave its group.
                setDragOrderSessionId(session.id);
                event.dataTransfer.setData(SESSION_TAB_ORDER_MIME, session.id);
                event.dataTransfer.effectAllowed = "move";
              }}
              onDragEnd={() => {
                setDragOrderSessionId(null);
                setDropTarget(null);
              }}
            >
              <VButton
                type="button"
                contentLayout="plain"
                className={[
                  styles.agentSessionTabGroupPanelItem,
                  sessionActive ? styles.agentSessionTabGroupPanelItemActive : "",
                ].filter(Boolean).join(" ")}
                title={session.title}
                onContextMenu={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onContextMenu(event, session);
                }}
                onPress={() => {
                  onOpenDirectSession(session.id);
                  setGroupOpen(section.groupId, false);
                }}
              >
                {renderAgentSessionStatusSlot(groupSessionTone(session))}
                <span className={styles.agentSessionTabGroupPanelTitle}>{session.title}</span>
              </VButton>
              <VIconButton
                type="button"
                variant="ghost"
                className={styles.agentSessionTabGroupPanelRemove}
                title={lang === "zh" ? "移出分组" : "Remove from group"}
                label={lang === "zh" ? "移出分组" : "Remove from group"}
                icon={<CornerUpLeft size={12} />}
                onPress={() => {
                  applyGroupMutation((state) => assignSessionToTabGroup(state, session.id, null));
                  setGroupOpen(section.groupId, false);
                }}
              />
            </li>
          );
        })}
      </ul>
    );
  };
  const renderSessionTabGroupHeader = (
    section: AgentSessionTabGroupSection,
    containsActive: boolean,
  ) => {
    // The ungrouped bucket is the default surface: no header, no label, no chrome.
    if (section.ungrouped) {
      return null;
    }
    const renaming = renamingGroupId === section.groupId;
    const dropActive = groupDropTarget === section.groupId;
    const aggregateTone = groupAggregateTone(section);
    const activeColor = sessionTabGroupColorFor(groupState, section.groupId);
    const groupDot = activeColor ? GROUP_DOT_CLASS[activeColor] : "";
    const isOpen = groupIsOpen(section.groupId);
    const headerClassName = [
      styles.agentSessionTabGroupHeader,
      // The accent ring says "the open session is in this group"; the group
      // colour belongs on the dot instead of tinting the whole chip.
      containsActive ? styles.agentSessionTabGroupHeaderActive : "",
      dropActive ? styles.agentSessionTabGroupHeaderDropTarget : "",
      isOpen ? styles.agentSessionTabGroupHeaderOpen : "",
    ].filter(Boolean).join(" ");
    const menu = groupMenu && groupMenu.groupId === section.groupId ? groupMenu : null;
    const menuItems: VDropdownMenuItem[] = [
      {
        id: "rename",
        label: lang === "zh" ? "重命名分组" : "Rename group",
        icon: <Pencil size={12} />,
        onSelect: () => {
          setGroupMenu(null);
          startGroupRename(section);
        },
      },
      ...TAB_GROUP_COLORS.map((color) => ({
        id: `color-${color}`,
        label: (
          <span className={styles.agentSessionTabGroupMenuItem}>
            <span
              className={[
                styles.agentSessionTabGroupSwatch,
                GROUP_SWATCH_CLASS[color],
                activeColor === color ? styles.agentSessionTabGroupSwatchActive : "",
              ].filter(Boolean).join(" ")}
              aria-hidden="true"
            />
            <span className={styles.agentSessionTabGroupMenuLabel}>
              {GROUP_COLOR_LABELS[color][lang === "zh" ? "zh" : "en"]}
            </span>
            {activeColor === color ? (
              <Check size={12} className={styles.agentSessionTabGroupMenuCheck} aria-hidden="true" />
            ) : null}
          </span>
        ),
        onSelect: () =>
          applyGroupMutation((state) =>
            setAgentSessionTabGroupColor(state, section.groupId, activeColor === color ? null : color),
          ),
      })),
      {
        id: "delete",
        label: lang === "zh" ? "删除分组" : "Delete group",
        icon: <Trash2 size={12} />,
        onSelect: () => {
          setGroupOpen(section.groupId, false);
          setGroupMenu(null);
          applyGroupMutation((state) => deleteAgentSessionTabGroup(state, section.groupId));
        },
      },
    ];
    return (
      <>
      <VPopover
        open={isOpen}
        onOpenChange={(open) => setGroupOpen(section.groupId, open)}
        side="bottom"
        align="start"
        sideOffset={6}
        aria-label={section.name}
        trigger={
          <div
            className={headerClassName}
            data-session-tab-group-header={section.groupId}
            data-session-tab-group-open={isOpen ? "true" : undefined}
            data-session-tab-group-tone={aggregateTone}
            title={lang === "zh" ? `${section.name} · ${section.sessions.length} 个会话` : `${section.name} · ${section.sessions.length} sessions`}
            onContextMenu={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setGroupMenu({ groupId: section.groupId, x: event.clientX, y: event.clientY });
            }}
          >
            {activeColor && activeColor !== "gray" ? (
              <span
                className={[styles.agentSessionTabGroupDot, groupDot].filter(Boolean).join(" ")}
                aria-hidden="true"
                data-group-dot={activeColor}
              />
            ) : null}
            {renderAgentSessionGroupStatus(groupToneCounts(section), lang)}
            {renaming ? (
              <span onPointerDown={(event) => event.stopPropagation()}>
                <VNativeInput
                  className={styles.agentSessionTabGroupNameInput}
                  value={groupNameDraft}
                  maxLength={40}
                  autoFocus
                  placeholder={lang === "zh" ? "分组名称" : "Group name"}
                  aria-label={lang === "zh" ? "分组名称" : "Group name"}
                  onChange={(event) => setGroupNameDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      commitGroupRename(section.groupId);
                    }
                    if (event.key === "Escape") {
                      event.preventDefault();
                      setRenamingGroupId(null);
                      setGroupNameDraft("");
                    }
                  }}
                  onBlur={() => commitGroupRename(section.groupId)}
                />
              </span>
            ) : (
              <span className={styles.agentSessionTabGroupName}>{section.name}</span>
            )}
            <span className={styles.agentSessionTabGroupCount}>{section.sessions.length}</span>
            <span
              className={[
                styles.agentSessionTabGroupChevron,
                section.collapsed ? styles.agentSessionTabGroupChevronCollapsed : "",
              ].filter(Boolean).join(" ")}
              aria-hidden="true"
              data-group-chevron
            >
              {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </span>
          </div>
        }
      >
        {renderGroupPopoverList(section)}
      </VPopover>
      {menu ? (
        <VDropdownMenu
          open
          position={{ x: menu.x, y: menu.y }}
          items={menuItems}
          contentClassName={styles.agentSessionTabGroupMenu}
          itemClassName={styles.agentSessionTabGroupMenuRow}
          aria-label={lang === "zh" ? "分组设置" : "Group settings"}
          onOpenChange={(next) => {
            if (!next) {
              setGroupMenu(null);
            }
          }}
        />
      ) : null}
      </>
    );
  };
  const commitTabOrderDrop = useCallback((targetId: string, position: "before" | "after") => {
    if (!dragOrderSessionId || dragOrderSessionId === targetId) {
      setDragOrderSessionId(null);
      return;
    }
    const next = reorderSessionIds(
      visibleSessions.map((session) => session.id),
      dragOrderSessionId,
      targetId,
      position,
    );
    persistAgentSessionTabOrder(agentTabScopeId, next);
    setDragOrderSessionId(null);
    setManualOrderTick((tick) => tick + 1);
  }, [agentTabScopeId, dragOrderSessionId, visibleSessions]);
  const tabGroupRef = useRef<HTMLDivElement>(null);
  // Two-stage inline confirm for tab close: at most one armed control at a time.
  const [armedCloseSessionId, setArmedCloseSessionId] = useState<string | null>(null);
  /** Right-click config surface for a tab group: rename / colour / collapse / delete. */
  const [groupMenu, setGroupMenu] = useState<{ groupId: string; x: number; y: number } | null>(null);
  /**
   * Open group panels live in memory only: a reload always starts closed so the
   * workbench never opens with floating panels over the conversation.
   */
  const [openGroupIds, setOpenGroupIds] = useState<string[]>([]);
  const groupIsOpen = (groupId: string) => openGroupIds.includes(groupId);
  const setGroupOpen = useCallback((groupId: string, open: boolean) => {
    setOpenGroupIds((current) => {
      if (open) {
        return current.includes(groupId) ? current : [...current, groupId];
      }
      return current.includes(groupId) ? current.filter((id) => id !== groupId) : current;
    });
  }, []);
  const rapidCloseUntilRef = useRef(0);
  const disarmCloseConfirm = useCallback(() => setArmedCloseSessionId(null), []);
  useEffect(() => {
    if (!armedCloseSessionId) {
      return;
    }
    const timeout = window.setTimeout(() => setArmedCloseSessionId(null), CLOSE_CONFIRM_ARM_TIMEOUT_MS);
    const isEventInsideArmedControl = (event: Event) => (
      event.target instanceof Element
      && Boolean(event.target.closest('[data-session-tab-close-armed="true"]'))
    );
    const handleDocumentPointerDown = (event: Event) => {
      // A press inside the armed control is the confirm click; anywhere else disarms.
      if (!isEventInsideArmedControl(event)) {
        setArmedCloseSessionId(null);
      }
    };
    const handleDocumentKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setArmedCloseSessionId(null);
      }
    };
    document.addEventListener("pointerdown", handleDocumentPointerDown, true);
    document.addEventListener("keydown", handleDocumentKeyDown);
    return () => {
      window.clearTimeout(timeout);
      document.removeEventListener("pointerdown", handleDocumentPointerDown, true);
      document.removeEventListener("keydown", handleDocumentKeyDown);
    };
  }, [armedCloseSessionId]);
  // Escape also ends the rapid-close burst. This listener must live outside the
  // armed-scoped effect above: after a confirmed close nothing is armed, so the
  // armed effect (and its keydown handler) is already torn down.
  useEffect(() => {
    const handleDocumentKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        rapidCloseUntilRef.current = 0;
      }
    };
    document.addEventListener("keydown", handleDocumentKeyDown);
    return () => document.removeEventListener("keydown", handleDocumentKeyDown);
  }, []);
  useEffect(() => {
    const activeTab = tabGroupRef.current?.querySelector<HTMLElement>('[data-session-tab-active="true"]');
    activeTab?.closest<HTMLElement>("[data-agent-session-tab-container]")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeSessionId, activeCliAgentRunId, workspaceActiveTab, sessions.length, cliAgentRuns.length]);
  const approvalSessionIds = new Set(
    sessionIdsNeedingApproval.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const runtimeSessionIds = new Set(
    runtimeRunningSessionIds.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const optimisticSessionIds = new Set(
    optimisticRunningSessionIds.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const navigationTabs = [
    ...visibleSessions.map((session) => ({ kind: "session" as const, id: session.id })),
    ...cliAgentRuns.map((run) => ({ kind: "cli" as const, id: run.id })),
  ];
  const keyboardTabs = navigationTabs.filter((tab) => (
    tab.kind !== "session" || tab.id !== editingSessionId
  ));
  const activeKeyboardTabIndex = Math.max(
    0,
    keyboardTabs.findIndex((tab) => (
      activeCliAgentRunId
        ? tab.kind === "cli" && tab.id === activeCliAgentRunId
        : tab.kind === "session" && tab.id === activeSessionId
    )),
  );
  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    tabIndex: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (tabIndex + 1) % keyboardTabs.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (tabIndex - 1 + keyboardTabs.length) % keyboardTabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = keyboardTabs.length - 1;
    }
    if (nextIndex === null || nextIndex < 0) {
      return;
    }
    const nextTab = keyboardTabs[nextIndex];
    if (!nextTab) {
      return;
    }
    event.preventDefault();
    if (nextTab.kind === "session") {
      if (activeSessionId === nextTab.id) {
        onSetActiveTab(nextTab.id, "agent");
      } else {
        onOpenDirectSession(nextTab.id);
      }
    } else {
      onOpenCliAgentRun?.(nextTab.id);
    }
    requestAnimationFrame(() => {
      document.getElementById(agentSessionTabElementId(nextTab.kind, nextTab.id))?.focus();
    });
  };

  return (
    <div className={styles.sessionHeader}>
    <div className={styles.agentSessionTabRail}>
      <div
        className={styles.agentSessionTabGroup}
        ref={tabGroupRef}
        role={keyboardTabs.length > 0 || paneDockChips.length > 0 || railRowTabs.length > 0 ? "tablist" : undefined}
        aria-label={keyboardTabs.length > 0 || paneDockChips.length > 0 || railRowTabs.length > 0 ? (lang === "zh" ? "Agent 会话" : "Agent sessions") : undefined}
        data-pane-dock-target="session-bar"
        onDragOver={(event) => {
          if (!onPaneDockDrop || !event.dataTransfer?.types.includes(PANE_DOCK_MIME)) {
            return;
          }
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
        }}
        onDrop={(event) => {
          const payload = readPaneDock(event.dataTransfer);
          if (!payload || payload.source !== "rail" || !onPaneDockDrop) {
            return;
          }
          event.preventDefault();
          onPaneDockDrop(payload);
        }}
      >
      {groupSections.map((section) => {
        // The active session keeps a real tab on the rail: "where am I" never needs a click.
        const pinnedSession = section.ungrouped
          ? undefined
          : section.sessions.find((session) => session.id === activeSessionId);
        return (
        <div
          key={section.groupId}
          className={[
            styles.agentSessionTabGroupSection,
            section.collapsed ? styles.agentSessionTabGroupSectionCollapsed : "",
            groupDropTarget === section.groupId ? styles.agentSessionTabGroupSectionDropTarget : "",
          ].filter(Boolean).join(" ")}
          data-session-tab-group={section.groupId}
          data-session-tab-group-ungrouped={section.ungrouped ? "true" : undefined}
          data-group-color={sessionTabGroupColorFor(groupState, section.groupId) ?? undefined}
          onDragOver={(event) => {
            if (!dragOrderSessionId) {
              return;
            }
            event.preventDefault();
            event.stopPropagation();
            event.dataTransfer.dropEffect = "move";
            setGroupDropTarget(section.groupId);
          }}
          onDragLeave={() => {
            setGroupDropTarget((current) => (current === section.groupId ? null : current));
          }}
          onDrop={(event) => {
            if (!dragOrderSessionId) {
              return;
            }
            event.preventDefault();
            event.stopPropagation();
            commitGroupDrop(section.groupId);
          }}
        >
          {renderSessionTabGroupHeader(section, Boolean(pinnedSession))}
          {section.ungrouped
            ? section.sessions.map((session) => renderSessionTab(session, section.groupId))
            : pinnedSession
              ? renderSessionTab(pinnedSession, section.groupId)
              : null}
        </div>
        );
      })}
      <VIconButton
        type="button"
        variant="ghost"
        className={styles.agentSessionTabGroupCreateButton}
        onPress={startGroupCreate}
        title={lang === "zh" ? "新建分组" : "New group"}
        label={lang === "zh" ? "新建分组" : "New group"}
        icon={<FolderPlus size={14} />}
      />
      {paneDockChips.map((chip) => {
        const tabClassName = [
          styles.agentSessionTab,
          chip.active ? styles.agentSessionTabActive : "",
        ].filter(Boolean).join(" ");
        const closeLabel = lang === "zh" ? "关闭" : "Close";
        return (
          <div
            key={chip.key}
            className={`${tabClassName} ${styles.agentSessionTabClosable}`}
            role="presentation"
            data-selected={chip.active ? "true" : undefined}
            data-pane-dock-chip={chip.tabId}
            draggable
            onDragStart={(event) => {
              writePaneDock(event.dataTransfer, {
                v: 1,
                source: "rail",
                tabId: chip.tabId,
                sessionId: chip.sessionId,
                scope: chip.scope,
              });
              if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
              }
            }}
          >
            <VButton
              type="button"
              contentLayout="plain"
              className={chip.active ? `${styles.agentSessionTabMainAction} ${styles.agentSessionTabMainActionActive}` : styles.agentSessionTabMainAction}
              role="tab"
              aria-selected={chip.active}
              data-session-tab-active={chip.active ? "true" : "false"}
              onPress={() => onPaneDockChipSelect?.(chip)}
              title={chip.title}
              aria-label={chip.title}
            >
              <span className={styles.agentSessionTabTitle}>{chip.title}</span>
            </VButton>
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.agentSessionTabCloseButton}
              onClick={(event) => {
                event.stopPropagation();
                onPaneDockChipClose?.(chip);
              }}
              title={closeLabel}
              label={`${closeLabel} ${chip.title}`}
              icon={<X size={13} />}
            />
          </div>
        );
      })}
      {railRowTabs.map((tab) => {
        const tabClassName = [
          styles.agentSessionTab,
          tab.active ? styles.agentSessionTabActive : "",
        ].filter(Boolean).join(" ");
        const closeLabel = lang === "zh" ? "关闭" : "Close";
        return (
          <div
            key={tab.id}
            className={`${tabClassName} ${styles.agentSessionTabClosable}`}
            role="presentation"
            data-selected={tab.active ? "true" : undefined}
            data-session-rail-tab={tab.id}
            draggable
            onDragStart={(event) => {
              writePaneDock(event.dataTransfer, {
                v: 1,
                source: "rail",
                tabId: tab.id,
              });
              if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
              }
            }}
          >
            <VButton
              type="button"
              contentLayout="plain"
              className={tab.active ? `${styles.agentSessionTabMainAction} ${styles.agentSessionTabMainActionActive}` : styles.agentSessionTabMainAction}
              role="tab"
              aria-selected={tab.active}
              data-session-tab-active={tab.active ? "true" : "false"}
              onPress={() => onRailRowTabSelect?.(tab.id)}
              title={tab.title}
              aria-label={tab.title}
            >
              <span className={styles.agentSessionTabTitle}>{tab.title}</span>
            </VButton>
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.agentSessionTabCloseButton}
              onClick={(event) => {
                event.stopPropagation();
                onRailRowTabClose?.(tab.id);
              }}
              title={closeLabel}
              label={`${closeLabel} ${tab.title}`}
              icon={<X size={13} />}
            />
          </div>
        );
      })}
      {cliAgentRuns.map((run) => {
        const tabActive = activeCliAgentRunId === run.id;
        const statusTone = agentSessionStatusTone(run.status);
        const statusShortLabel = agentSessionStatusShortLabel(statusTone, lang);
        const title = [run.title, statusShortLabel, run.summary].filter(Boolean).join(" · ");
        const tabMainActionClassName = [
          styles.agentSessionTabMainAction,
          tabActive ? styles.agentSessionTabMainActionActive : "",
        ].filter(Boolean).join(" ");
        const tabClassName = [
          styles.agentSessionTab,
          styles.agentSessionTabCli,
          tabActive ? styles.agentSessionTabActive : "",
        ].filter(Boolean).join(" ");
        const keyboardIndex = keyboardTabs.findIndex((tab) => tab.kind === "cli" && tab.id === run.id);
        return (
          <div
            key={run.id}
            className={`${tabClassName} ${styles.agentSessionTabClosable}`}
            role="presentation"
            data-selected={tabActive ? "true" : undefined}
            data-agent-session-tab-container
          >
            <VButton
              type="button"
              contentLayout="plain"
              className={tabMainActionClassName}
              id={agentSessionTabElementId("cli", run.id)}
              role="tab"
              aria-selected={tabActive}
              aria-current={tabActive ? "true" : undefined}
              tabIndex={keyboardIndex === activeKeyboardTabIndex ? 0 : -1}
              onKeyDown={(event) => handleTabKeyDown(event, keyboardIndex)}
              data-session-tab-active={tabActive ? "true" : "false"}
              onPress={() => onOpenCliAgentRun?.(run.id)}
              title={title}
              aria-label={
                tabActive
                  ? (statusShortLabel
                    ? `${lang === "zh" ? "当前终端" : "Current terminal"}: ${run.title} · ${statusShortLabel}`
                    : `${lang === "zh" ? "当前终端" : "Current terminal"}: ${run.title}`)
                  : (statusShortLabel ? `${run.title} · ${statusShortLabel}` : run.title)
              }
            >
              <span
                className={[
                  styles.agentSessionTabIcon,
                  tabActive ? styles.agentSessionTabIconActive : "",
                ].filter(Boolean).join(" ")}
                aria-hidden="true"
              >
                <SquareTerminal size={14} />
              </span>
              <span className={styles.agentSessionTabTitleBlock}>
                <span
                  className={[
                    styles.agentSessionTabTitle,
                    tabActive ? styles.agentSessionTabTitleActive : "",
                  ].filter(Boolean).join(" ")}
                >{run.title}</span>
              </span>
              {renderAgentSessionStatusSlot(statusTone)}
            </VButton>
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.agentSessionTabCloseButton}
              onClick={(event) => {
                event.stopPropagation();
                onCloseCliAgentRun?.(run.id);
              }}
              title={lang === "zh" ? "关闭终端页" : "Close terminal tab"}
              label={`${lang === "zh" ? "关闭终端页" : "Close terminal tab"} ${run.title}`}
              icon={<X size={13} />}
            />
          </div>
        );
      })}
      </div>
      {editingSessionId ? null : (
        <VIconButton
          type="button"
          variant="ghost"
          className={styles.agentSessionTabCreateButton}
          onPress={onCreateSession}
          isDisabled={createPending || createDisabled}
          title={lang === "zh" ? "在当前 Agent 下新建会话" : "New session for current Agent"}
          label={lang === "zh" ? "在当前 Agent 下新建会话" : "New session for current Agent"}
          icon={<Plus size={14} />}
        />
      )}
    </div>
    </div>
  );
}
