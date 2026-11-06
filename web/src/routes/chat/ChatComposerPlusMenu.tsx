import {
  Activity,
  ArrowUpRight,
  BookOpen,
  BrainCircuit,
  Check,
  Clock3,
  CornerDownLeft,
  Gauge,
  ImagePlus,
  KeyRound,
  MessageCircleHeart,
  MessageSquare,
  Plus,
  Settings2,
  Sparkles,
  UsersRound,
} from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import type { SessionReferenceAttachment } from "../../api/types";
import { VButton, VDialog, VInput, VNativeInput, VPopover, VStateSurface } from "../../components/vui";
import { rankByScore } from "../../components/conversation/conversationFuzzyMatch";
import { ConversationComposerActionsContext } from "../../components/conversation/ConversationComposerActionsContext";
import { ChatComposerBudgetPopover, type ChatComposerBudgetControl, type ChatComposerBudgetPanelLabels } from "./ChatComposerBudgetPopover";
import { composerAttachmentAcceptAttribute } from "./chatComposerSubmitModel";
import styles from "./ChatComposerPlusMenu.styles";

export type ChatComposerSessionReferenceOption = {
  id: string;
  title: string;
  meta?: string;
  reference: SessionReferenceAttachment;
};

export type ChatComposerKnowledgeReferenceState = {
  loading: boolean;
  error: boolean;
  onRequest: () => void;
};

/** Privacy attachment surface (personal assistant only). The dialog collects an
 * optional display label and the plaintext; the host stages the value through
 * its closed IPC and receives a `sec_` reference. The plaintext lives only in
 * this dialog's controlled input state and is dropped on success, close or
 * unmount — it never enters a draft, snapshot or storage. */
export type ChatComposerSecretAttachmentInput = {
  value: string;
  label?: string;
};

/** A live assistant `secret_request` receipt (the model asked the operator for
 * a private credential). Null or omitted renders nothing, so ordinary chats
 * never see the banner. */
export type ChatComposerSecretRequest = {
  purpose: string;
  label?: string;
};

/** A scoped workspace can supply its existing directory without enabling global queries. */
export type ChatComposerScopedSessionReferences = {
  options: ChatComposerSessionReferenceOption[];
  hasMore?: boolean;
  loadingMore?: boolean;
  loadMoreError?: boolean;
  onLoadMore?: () => void;
};
export const ChatComposerSessionReferencesContext = createContext<ChatComposerScopedSessionReferences | null>(null);

export type ChatComposerPlusMenuLabels = {
  composerAttachFiles: string;
  composerReferenceKnowledgeFiles: string;
  composerReferenceKnowledgeUnavailable: string;
  composerReferenceKnowledgeTitle: string;
  composerReferenceKnowledgeDescription: string;
  composerReferenceKnowledgeSearch: string;
  composerReferenceKnowledgeEmpty: string;
  composerBudgetEntry: string;
  composerBudgetHint: string;
} & ChatComposerBudgetPanelLabels;

type ChatComposerCapabilities = {
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  promptSuggestionEnabled: boolean;
  capabilityDisabled: boolean;
  onMentalModelEnabledChange: (enabled: boolean) => void;
  onRuntimeStatusEnabledChange: (enabled: boolean) => void;
  onPromptSuggestionEnabledChange: (enabled: boolean) => void;
};

type ChatComposerCapabilityProps = ({ showCapabilities?: true } & ChatComposerCapabilities)
  | ({ showCapabilities: false } & Partial<ChatComposerCapabilities>);

export type ChatComposerPlusMenuProps = ChatComposerCapabilityProps & {
  lang: "zh" | "en";
  labels?: ChatComposerPlusMenuLabels;
  showAddReference?: boolean;
  /** Native hosts can reuse the attachment menu without unsupported references. */
  showReferences?: boolean;
  attachmentDisabled: boolean;
  onAddAttachments?: (files: FileList | File[]) => void;
  /** Privacy attachment entry; omitted surfaces get no menu item (ordinary
   * chats never pass it, so their plus menu stays bit-for-bit identical). */
  onAttachSecret?: (input: ChatComposerSecretAttachmentInput) => Promise<void>;
  /** A pending assistant `secret_request` receipt; renders a one-click request
   * banner near the composer until attached or dismissed. Hidden while the
   * private attachment dialog is open so the two never stack. */
  secretRequest?: ChatComposerSecretRequest | null;
  /** The operator ignored the current request; the host keys the dismissal. */
  onSecretRequestDismiss?: () => void;
  sessionReferences: ChatComposerSessionReferenceOption[];
  onAddSessionReference?: (reference: SessionReferenceAttachment) => void;
  knowledgeReferenceOptions?: ChatComposerSessionReferenceOption[];
  knowledgeReferenceState?: ChatComposerKnowledgeReferenceState;
  onAddKnowledgeReference?: (reference: SessionReferenceAttachment) => void;
  /** Per-session budget/quota control; omitted surfaces get no menu entry. */
  budget?: ChatComposerBudgetControl | null;
  directSession?: {
    id: string;
    label: string;
    onOpen: () => void;
    onPrefetch?: () => void;
  } | null;
  group?: {
    title: string;
    onManage: () => void;
    teamId?: string;
    onOpenTeam?: () => void;
  } | null;
};

type SectionDescriptor = {
  id: string;
  label: string;
};

function ItemIcon({ children }: { children: ReactNode }) {
  return (
    <span
      data-slot="menu-item-icon"
      aria-hidden="true"
      className={styles.itemIcon}
    >
      {children}
    </span>
  );
}

export function ChatComposerPlusMenu(props: ChatComposerPlusMenuProps) {
  const deliveryActions = useContext(ConversationComposerActionsContext);
  const {
    lang,
    labels,
    showAddReference = true,
    showReferences = true,
    attachmentDisabled,
    onAddAttachments,
    onAttachSecret,
    secretRequest,
    onSecretRequestDismiss,
    sessionReferences: defaultSessionReferences,
    onAddSessionReference,
    knowledgeReferenceOptions,
    knowledgeReferenceState,
    onAddKnowledgeReference,
    budget,
    directSession,
    group,
  } = props;
  const scopedSessionReferences = useContext(ChatComposerSessionReferencesContext);
  const sessionReferences = scopedSessionReferences?.options ?? defaultSessionReferences;
  const canLoadMoreReferences = Boolean(scopedSessionReferences?.hasMore && scopedSessionReferences.onLoadMore);
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const composerAnchorRef = useRef<HTMLElement | null>(null);
  const [hasComposerAnchor, setHasComposerAnchor] = useState(false);
  const captureComposerAnchor = useCallback((node: HTMLButtonElement | null) => {
    const anchor = node?.closest<HTMLElement>(".composerCodex, .composer") ?? null;
    composerAnchorRef.current = anchor;
    setHasComposerAnchor(Boolean(anchor));
  }, []);
  const [open, setOpen] = useState(false);
  const [referenceDialogOpen, setReferenceDialogOpen] = useState(false);
  const [referenceQuery, setReferenceQuery] = useState("");
  const [knowledgeDialogOpen, setKnowledgeDialogOpen] = useState(false);
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  // Privacy attachment dialog state. `secretValue` is the only place the
  // plaintext ever lives renderer-side; every exit path clears it immediately.
  const [secretDialogOpen, setSecretDialogOpen] = useState(false);
  const [secretLabel, setSecretLabel] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [secretPending, setSecretPending] = useState(false);
  const [secretError, setSecretError] = useState("");

  const addReferenceSection = useMemo<SectionDescriptor>(() => ({
    id: "add-reference",
    label: lang === "zh" ? "添加与引用" : "Add and reference",
  }), [lang]);
  const capabilitiesSection = useMemo<SectionDescriptor>(() => ({
    id: "conversation-capabilities",
    label: lang === "zh" ? "对话能力" : "Conversation capabilities",
  }), [lang]);
  const companionSection = useMemo<SectionDescriptor>(() => ({
    id: "session-companion",
    label: lang === "zh" ? "会话与陪伴" : "Session and companion",
  }), [lang]);
  const groupSection = useMemo<SectionDescriptor>(() => ({
    id: "group-team",
    label: lang === "zh" ? "群聊与团队" : "Group and team",
  }), [lang]);

  const filteredReferences = useMemo(() => {
    const query = referenceQuery.trim().toLocaleLowerCase();
    if (!query) {
      return sessionReferences;
    }
    return rankByScore(sessionReferences, query, (option) =>
      `${option.title} ${option.meta ?? ""}`.toLocaleLowerCase(),
    );
  }, [referenceQuery, sessionReferences]);

  const filteredKnowledgeReferences = useMemo(() => {
    const query = knowledgeQuery.trim().toLocaleLowerCase();
    const options = knowledgeReferenceOptions ?? [];
    if (!query) {
      return options;
    }
    return rankByScore(options, query, (option) =>
      `${option.title} ${option.meta ?? ""}`.toLocaleLowerCase(),
    );
  }, [knowledgeQuery, knowledgeReferenceOptions]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      focusMenuItem(menuRef.current, 0);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  function focusMenuItem(container: HTMLDivElement | null, index: number) {
    const items = menuItems(container);
    if (items.length === 0) {
      return;
    }
    const nextIndex = (index + items.length) % items.length;
    items[nextIndex]?.focus();
  }

  function menuItems(container: HTMLDivElement | null): HTMLButtonElement[] {
    if (!container) {
      return [];
    }
    return Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]:not([disabled])'),
    );
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = menuItems(menuRef.current);
    if (items.length === 0) {
      return;
    }
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusMenuItem(menuRef.current, index === -1 ? 0 : index + 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      focusMenuItem(menuRef.current, index === -1 ? items.length - 1 : index - 1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      focusMenuItem(menuRef.current, 0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      focusMenuItem(menuRef.current, items.length - 1);
    }
  }

  function closeMenu() {
    setOpen(false);
  }

  function selectAction(action: () => void) {
    closeMenu();
    action();
  }

  function resetSecretDraft() {
    setSecretLabel("");
    setSecretValue("");
    setSecretError("");
  }

  function changeSecretDialogOpen(nextOpen: boolean) {
    setSecretDialogOpen(nextOpen);
    if (!nextOpen) {
      // Any exit (cancel, escape, backdrop) burns the draft: write-only.
      resetSecretDraft();
    }
  }

  /** The request banner's one-click path into the same dialog the plus menu
   * uses. The suggested display name prefills only while the operator has not
   * typed one; a closed dialog always resets the label, so this fills just the
   * assistant's suggestion and never overwrites a manual entry. */
  function openSecretRequestDialog() {
    setSecretError("");
    if (secretRequest?.label && !secretLabel.trim()) {
      setSecretLabel(secretRequest.label);
    }
    setSecretDialogOpen(true);
  }

  async function submitSecretAttachment() {
    if (!onAttachSecret || secretPending || !secretValue.trim()) return;
    setSecretPending(true);
    setSecretError("");
    const trimmedLabel = secretLabel.trim();
    try {
      await onAttachSecret({
        value: secretValue,
        ...(trimmedLabel ? { label: trimmedLabel } : {}),
      });
      // Staged: the host now holds only the `sec_` reference. Drop the plaintext.
      resetSecretDraft();
      setSecretDialogOpen(false);
    } catch (error) {
      // Failure keeps the dialog open with the value intact for a correction;
      // the state is in-memory only and still never reaches storage.
      setSecretError(error instanceof Error && error.message ? error.message
        : lang === "zh" ? "隐私附件提交失败，请重试。" : "Could not stage the private attachment; try again.");
    } finally {
      setSecretPending(false);
    }
  }

  function renderSection(section: SectionDescriptor, children: ReactNode) {
    return (
      <div
        key={section.id}
        className={styles.section}
        role="group"
        aria-label={section.label}
        data-testid={`chat-composer-plus-${section.id}`}
      >
        <div className={styles.sectionTitle}>{section.label}</div>
        {children}
      </div>
    );
  }

  function renderAction(options: {
    id: string;
    label: string;
    icon: ReactNode;
    disabled?: boolean;
    disabledReason?: string;
    title?: string;
    onSelect: () => void;
  }) {
    return (
      <VButton
        key={options.id}
        type="button"
        role="menuitem"
        data-plus-menu-item="true"
        contentLayout="plain"
        className={styles.menuItem}
        variant="ghost"
        isDisabled={options.disabled}
        title={options.title}
        disabledReason={options.disabled ? options.disabledReason : undefined}
        onPress={() => selectAction(options.onSelect)}
      >
        <ItemIcon>{options.icon}</ItemIcon>
        <span className={styles.itemLabel}>{options.label}</span>
      </VButton>
    );
  }

  function renderToggle(options: {
    id: string;
    label: string;
    hint: string;
    icon: ReactNode;
    checked: boolean;
    disabled?: boolean;
    onChange: (checked: boolean) => void;
  }) {
    const stateLabel = options.checked ? (lang === "zh" ? "开启" : "On") : (lang === "zh" ? "关闭" : "Off");
    return (
      <VButton
        key={options.id}
        type="button"
        role="menuitemcheckbox"
        aria-checked={options.checked}
        aria-label={`${options.label}：${stateLabel}`}
        data-plus-menu-item="true"
        contentLayout="plain"
        className={options.checked ? `${styles.menuItem} ${styles.menuItemChecked}` : styles.menuItem}
        variant="ghost"
        isDisabled={options.disabled}
        onPress={() => options.onChange(!options.checked)}
      >
        <ItemIcon>{options.icon}</ItemIcon>
        <span className={styles.itemCopy}>
          <strong className={styles.itemTitle}>{options.label}</strong>
          <small className={styles.itemHint}>{options.hint}</small>
        </span>
        <span aria-hidden="true" className={styles.itemCheck}>
          {options.checked ? <Check size={15} /> : null}
        </span>
      </VButton>
    );
  }

  const defaultLabels: ChatComposerPlusMenuLabels = lang === "zh"
    ? {
        composerAttachFiles: "添加附件",
        composerReferenceKnowledgeFiles: "引用知识/文件",
        composerReferenceKnowledgeUnavailable: "当前没有可引用的知识或文件",
        composerReferenceKnowledgeTitle: "引用知识与文件",
        composerReferenceKnowledgeDescription: "把知识库、知识条目或本会话文件作为本轮上下文引用。",
        composerReferenceKnowledgeSearch: "搜索知识与文件",
        composerReferenceKnowledgeEmpty: "没有匹配的知识或文件。",
        composerBudgetEntry: "预算与额度",
        composerBudgetHint: "每回合工具调用次数",
        composerBudgetTitle: "预算与额度",
        composerBudgetDescription: "按会话限制每回合工具调用次数；清除后回到默认策略。",
        composerBudgetMaxCallsLabel: "每回合工具调用额度",
        composerBudgetMaxCallsPlaceholder: "未配置=按模型策略，常见 32",
        composerBudgetClearMaxCalls: "清除工具调用额度，恢复默认",
        composerBudgetSave: "保存",
        composerBudgetCancel: "取消",
        composerBudgetLoading: "读取预算配置…",
        composerBudgetLoadFailed: "预算配置读取失败",
        composerBudgetUnlimited: "不限制工具调用次数（关闭每回合预算）",
        composerBudgetUnlimitedHint: "开启后本会话不再按回合限制工具调用；仍受工具授权与迭代上限约束。",
      }
    : {
        composerAttachFiles: "Attach files",
        composerReferenceKnowledgeFiles: "Reference knowledge or files",
        composerReferenceKnowledgeUnavailable: "No knowledge or files are available to reference",
        composerReferenceKnowledgeTitle: "Reference knowledge and files",
        composerReferenceKnowledgeDescription: "Attach knowledge bases, entries, or session files as context for this turn.",
        composerReferenceKnowledgeSearch: "Search knowledge and files",
        composerReferenceKnowledgeEmpty: "No matching knowledge or files.",
        composerBudgetEntry: "Budget and quota",
        composerBudgetHint: "Per-turn tool calls",
        composerBudgetTitle: "Budget and quota",
        composerBudgetDescription: "Limit per-turn tool calls for this session; clearing restores defaults.",
        composerBudgetMaxCallsLabel: "Tool calls per turn",
        composerBudgetMaxCallsPlaceholder: "Unset = model policy, commonly 32",
        composerBudgetClearMaxCalls: "Clear tool-call quota, restore default",
        composerBudgetSave: "Save",
        composerBudgetCancel: "Cancel",
        composerBudgetLoading: "Loading budget settings…",
        composerBudgetLoadFailed: "Failed to load budget settings",
        composerBudgetUnlimited: "No per-turn tool-call limit",
        composerBudgetUnlimitedHint: "Removes the per-turn cap for this session; tool authorization and the iteration limit still apply.",
      };
  const resolvedLabels = { ...defaultLabels, ...labels };
  const t = (key: keyof ChatComposerPlusMenuLabels) => resolvedLabels[key];
  const attachmentUnavailableReason = lang === "zh" ? "当前会话暂不可添加附件" : "Attachments are unavailable in this session";
  const referenceUnavailableReason = lang === "zh" ? "没有可引用的历史会话" : "No previous session is available to reference";
  const knowledgeUnavailableReason = t("composerReferenceKnowledgeUnavailable");

  return (
    <>
      {secretRequest && !secretDialogOpen ? (
        <VStateSurface
          density="compact"
          tone="info"
          role="status"
          data-testid="chat-composer-secret-request"
          className={styles.secretRequestBar}
          icon={<KeyRound size={14} aria-hidden="true" />}
          title={`${lang === "zh" ? "助理请求隐私内容：" : "Assistant requests private content: "}${secretRequest.purpose}`}
          actions={<>
            <VButton type="button" onPress={openSecretRequestDialog}>
              {lang === "zh" ? "立即附加" : "Attach now"}
            </VButton>
            <VButton type="button" variant="ghost" onPress={() => onSecretRequestDismiss?.()}>
              {lang === "zh" ? "忽略" : "Dismiss"}
            </VButton>
          </>}
        >
          {secretRequest.label
            ? lang === "zh" ? `建议显示名：${secretRequest.label}` : `Suggested display name: ${secretRequest.label}`
            : null}
        </VStateSurface>
      ) : null}
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
        }}
        side="top"
        align="start"
        sideOffset={8}
        aria-label={lang === "zh" ? "更多操作" : "More actions"}
        anchorRef={hasComposerAnchor ? composerAnchorRef : undefined}
        contentClassName={[styles.popoverContent, hasComposerAnchor ? styles.composerWidth : styles.standaloneWidth].join(" ")}
        trigger={(
          <VButton
            ref={captureComposerAnchor}
            type="button"
            isIconOnly
            variant="ghost"
            className={styles.trigger}
            aria-label={lang === "zh" ? "更多操作" : "More actions"}
            icon={<Plus size={16} />}
          />
        )}
      >
        <div
          ref={menuRef}
          className={styles.menu}
          role="menu"
          aria-label={lang === "zh" ? "更多操作菜单" : "More actions menu"}
          onKeyDown={handleMenuKeyDown}
        >
          {deliveryActions.length ? renderSection({ id: "delivery", label: lang === "zh" ? "发送方式" : "Delivery" },
            deliveryActions.map(action => renderAction({
              ...action,
              icon: action.id === "queue" ? <Clock3 size={16} /> : <CornerDownLeft size={16} />,
              disabledReason: action.hint,
              title: action.hint,
            })),
          ) : null}
          {showAddReference ? renderSection(addReferenceSection, (
            <>
              {renderAction({
                id: "attach-image",
                label: t("composerAttachFiles"),
                icon: <ImagePlus size={16} />,
                disabled: attachmentDisabled || !onAddAttachments,
                disabledReason: attachmentUnavailableReason,
                onSelect: () => attachmentInputRef.current?.click(),
              })}
              {onAttachSecret ? renderAction({
                id: "attach-secret",
                label: lang === "zh" ? "隐私附件" : "Private attachment",
                icon: <KeyRound size={16} />,
                disabled: attachmentDisabled,
                disabledReason: attachmentUnavailableReason,
                onSelect: () => {
                  setSecretError("");
                  setSecretDialogOpen(true);
                },
              }) : null}
              {showReferences ? renderAction({
                id: "reference-session",
                label: lang === "zh" ? "引用会话" : "Reference session",
                icon: <MessageSquare size={16} />,
                disabled: !onAddSessionReference || (sessionReferences.length === 0 && !canLoadMoreReferences),
                disabledReason: referenceUnavailableReason,
                onSelect: () => {
                  setReferenceQuery("");
                  setReferenceDialogOpen(true);
                },
              }) : null}
              {showReferences ? renderAction({
                id: "reference-knowledge",
                label: t("composerReferenceKnowledgeFiles"),
                icon: <BookOpen size={16} />,
                disabled: !onAddKnowledgeReference || (!knowledgeReferenceState && (knowledgeReferenceOptions ?? []).length === 0),
                disabledReason: knowledgeUnavailableReason,
                onSelect: () => {
                  knowledgeReferenceState?.onRequest();
                  setKnowledgeQuery("");
                  setKnowledgeDialogOpen(true);
                },
              }) : null}
            </>
          )) : null}
          {props.showCapabilities !== false || budget ? renderSection(capabilitiesSection, (
            <>
              {props.showCapabilities !== false ? <>
              {renderToggle({
                id: "mental-model",
                label: lang === "zh" ? "心智模型" : "Mental model",
                hint: lang === "zh" ? "下轮生效" : "Applies next turn",
                icon: <BrainCircuit size={16} />,
                checked: props.mentalModelEnabled,
                disabled: props.capabilityDisabled,
                onChange: props.onMentalModelEnabledChange,
              })}
              {renderToggle({
                id: "runtime-status",
                label: lang === "zh" ? "运行状态注入" : "Runtime status injection",
                hint: lang === "zh" ? "把预算与进度注入上下文" : "Inject budget and progress into context",
                icon: <Activity size={16} />,
                checked: props.runtimeStatusEnabled,
                disabled: props.capabilityDisabled,
                onChange: props.onRuntimeStatusEnabledChange,
              })}
              {renderToggle({
                id: "prompt-suggestion",
                label: lang === "zh" ? "输入建议" : "Prompt suggestions",
                hint: lang === "zh" ? "回答后提示下一句，Tab 补全" : "Suggests the next prompt after a reply, Tab to complete",
                icon: <Sparkles size={16} />,
                checked: props.promptSuggestionEnabled,
                disabled: props.capabilityDisabled,
                onChange: props.onPromptSuggestionEnabledChange,
              })}
              </> : null}
              {budget ? (
                <ChatComposerBudgetPopover
                  lang={lang}
                  labels={resolvedLabels}
                  sessionId={budget.sessionId}
                  revision={budget.revision}
                  maxCallsPerTurn={budget.maxCallsPerTurn}
                  loading={budget.loading}
                  error={budget.error}
                  pending={budget.pending}
                  errorMessage={budget.errorMessage}
                  onSave={budget.onSave}
                  trigger={(
                    <VButton
                      type="button"
                      role="menuitem"
                      data-plus-menu-item="true"
                      contentLayout="plain"
                      className={styles.menuItem}
                      variant="ghost"
                      isDisabled={props.capabilityDisabled}
                    >
                      <ItemIcon><Gauge size={16} /></ItemIcon>
                      <span className={styles.itemLabel}>{t("composerBudgetEntry")}</span>
                    </VButton>
                  )}
                />
              ) : null}
            </>
          )) : null}
          {directSession ? renderSection(companionSection, (
            <>
              {renderAction({
                id: "open-direct-session",
                label: lang === "zh" ? "打开直接会话" : "Open direct session",
                icon: <ArrowUpRight size={16} />,
                onSelect: directSession.onOpen,
              })}
            </>
          )) : null}
          {group ? renderSection(groupSection, (
            <>
              {renderAction({
                id: "manage-group",
                label: lang === "zh" ? "管理群聊" : "Manage group",
                icon: <Settings2 size={16} />,
                onSelect: group.onManage,
              })}
              {group.teamId && group.onOpenTeam ? renderAction({
                id: "open-team",
                label: lang === "zh" ? "打开团队" : "Open team",
                icon: <UsersRound size={16} />,
                onSelect: group.onOpenTeam,
              }) : null}
            </>
          )) : null}
        </div>
      </VPopover>

      <VNativeInput
        ref={attachmentInputRef}
        className={styles.hiddenInput}
        type="file"
        accept={composerAttachmentAcceptAttribute()}
        multiple
        disabled={attachmentDisabled}
        aria-label={lang === "zh" ? "选择附件" : "Choose attachments"}
        onChange={(event) => {
          if (event.currentTarget.files && onAddAttachments) {
            onAddAttachments(event.currentTarget.files);
          }
          event.currentTarget.value = "";
        }}
      />

      <VDialog
        open={secretDialogOpen}
        onOpenChange={changeSecretDialogOpen}
        title={lang === "zh" ? "添加隐私附件" : "Add a private attachment"}
        description={lang === "zh" ? "内容经封闭通道直接暂存，聊天里只显示遮罩卡片，不会展示明文。" : "The value is staged through a closed channel; the chat shows a masked card and never the plaintext."}
        size="md"
      >
        <div className={styles.secretBody}>
          <label className={styles.secretField}>
            <span>{lang === "zh" ? "显示名（可选）" : "Display name (optional)"}</span>
            <VInput
              value={secretLabel}
              onChange={(event) => setSecretLabel(event.target.value)}
              placeholder={lang === "zh" ? "如：中转站密钥" : "e.g. Relay API key"}
              aria-label={lang === "zh" ? "隐私附件显示名" : "Private attachment display name"}
              autoComplete="off"
            />
          </label>
          <label className={styles.secretField}>
            <span>{lang === "zh" ? "内容" : "Value"}</span>
            <VInput
              type="password"
              autoComplete="new-password"
              value={secretValue}
              onChange={(event) => setSecretValue(event.target.value)}
              placeholder={lang === "zh" ? "粘贴隐私内容，仅此一次输入" : "Paste the private content; entered once only"}
              aria-label={lang === "zh" ? "隐私内容" : "Private value"}
            />
          </label>
          {secretError ? <p className={styles.secretError} role="alert">{secretError}</p> : null}
          <div className={styles.secretActions}>
            <VButton type="button" variant="ghost" isDisabled={secretPending}
              onPress={() => changeSecretDialogOpen(false)}>
              {lang === "zh" ? "取消" : "Cancel"}
            </VButton>
            <VButton type="button" isPending={secretPending} isDisabled={secretPending || !secretValue.trim()}
              onPress={() => void submitSecretAttachment()}>
              {lang === "zh" ? "添加" : "Add"}
            </VButton>
          </div>
        </div>
      </VDialog>

      <VDialog
        open={referenceDialogOpen}
        onOpenChange={(nextOpen) => {
          setReferenceDialogOpen(nextOpen);
          if (!nextOpen) {
            setReferenceQuery("");
          }
        }}
        title={lang === "zh" ? "引用会话" : "Reference session"}
        description={lang === "zh" ? "把一个历史会话作为本轮上下文引用。" : "Attach a previous session as context for this turn."}
        size="md"
      >
        <div className={styles.referenceBody}>
          <VNativeInput
            value={referenceQuery}
            onChange={(event) => setReferenceQuery(event.target.value)}
            placeholder={lang === "zh" ? "搜索会话" : "Search sessions"}
            aria-label={lang === "zh" ? "搜索会话" : "Search sessions"}
          />
          <div className={styles.referenceList} role="group" aria-label={lang === "zh" ? "可引用会话" : "Referenceable sessions"}>
            {filteredReferences.map((option) => (
              <VButton
                key={option.id}
                type="button"
                className={styles.referenceOption}
                variant="ghost"
                onPress={() => {
                  onAddSessionReference?.(option.reference);
                  setReferenceDialogOpen(false);
                  setReferenceQuery("");
                }}
              >
                <strong className={styles.referenceTitle}>{option.title}</strong>
                {option.meta ? <small className={styles.referenceMeta}>{option.meta}</small> : null}
              </VButton>
            ))}
            {filteredReferences.length === 0 ? (
              <p className={styles.referenceEmpty}>
                {lang === "zh" ? "没有匹配的会话。" : "No matching sessions."}
              </p>
            ) : null}
          </div>
          {scopedSessionReferences?.loadMoreError ? <p role="alert">{lang === "zh" ? "读取更多会话失败，请重试。" : "Could not load more sessions. Please retry."}</p> : null}
          {canLoadMoreReferences ? <VButton variant="secondary" isPending={scopedSessionReferences?.loadingMore} onPress={scopedSessionReferences?.onLoadMore}>{lang === "zh" ? "更多会话" : "More sessions"}</VButton> : null}
        </div>
      </VDialog>

      <VDialog
        open={knowledgeDialogOpen}
        onOpenChange={(nextOpen) => {
          setKnowledgeDialogOpen(nextOpen);
          if (!nextOpen) {
            setKnowledgeQuery("");
          }
        }}
        title={t("composerReferenceKnowledgeTitle")}
        description={t("composerReferenceKnowledgeDescription")}
        size="md"
      >
        <div className={styles.referenceBody}>
          <VNativeInput
            value={knowledgeQuery}
            onChange={(event) => setKnowledgeQuery(event.target.value)}
            placeholder={t("composerReferenceKnowledgeSearch")}
            aria-label={t("composerReferenceKnowledgeSearch")}
          />
          <div className={styles.referenceList} role="group" aria-label={t("composerReferenceKnowledgeTitle")}>
            {filteredKnowledgeReferences.map((option) => (
              <VButton
                key={option.id}
                type="button"
                className={styles.referenceOption}
                variant="ghost"
                onPress={() => {
                  onAddKnowledgeReference?.(option.reference);
                  setKnowledgeDialogOpen(false);
                  setKnowledgeQuery("");
                }}
              >
                <strong className={styles.referenceTitle}>{option.title}</strong>
                {option.meta ? <small className={styles.referenceMeta}>{option.meta}</small> : null}
              </VButton>
            ))}
            {knowledgeReferenceState?.loading && !knowledgeReferenceState.error ? <p className={styles.referenceEmpty} role="status">{lang === "zh" ? "正在加载知识与文件…" : "Loading knowledge and files…"}</p> : null}
            {knowledgeReferenceState?.error ? <div role="alert"><p>{lang === "zh" ? "知识与文件加载失败" : "Could not load knowledge and files"}</p><VButton variant="secondary" onPress={knowledgeReferenceState.onRequest}>{lang === "zh" ? "重试" : "Retry"}</VButton></div> : null}
            {filteredKnowledgeReferences.length === 0 && !knowledgeReferenceState?.loading && !knowledgeReferenceState?.error ? (
              <p className={styles.referenceEmpty}>
                {t("composerReferenceKnowledgeEmpty")}
              </p>
            ) : null}
          </div>
        </div>
      </VDialog>
    </>
  );
}
