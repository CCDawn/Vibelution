import {
  Activity,
  Apple,
  ArrowUpRight,
  BrainCircuit,
  ChevronRight,
  ImagePlus,
  MessageCircleHeart,
  MessageSquare,
  Plus,
  Settings2,
  UsersRound,
  HeartHandshake,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { SessionReferenceAttachment } from "../../api/types";
import { VButton, VDialog, VNativeInput, VPopover } from "../../components/vui";
import styles from "./ChatComposerPlusMenu.styles";

export type ChatComposerSessionReferenceOption = {
  id: string;
  title: string;
  meta?: string;
  reference: SessionReferenceAttachment;
};

export type ChatComposerPlusMenuProps = {
  lang: "zh" | "en";
  showAddReference?: boolean;
  showCapabilities?: boolean;
  attachmentDisabled: boolean;
  onAddAttachments?: (files: FileList | File[]) => void;
  sessionReferences: ChatComposerSessionReferenceOption[];
  onAddSessionReference?: (reference: SessionReferenceAttachment) => void;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  capabilityDisabled: boolean;
  onMentalModelEnabledChange: (enabled: boolean) => void;
  onRuntimeStatusEnabledChange: (enabled: boolean) => void;
  directSession?: {
    id: string;
    label: string;
    onOpen: () => void;
    onPrefetch?: () => void;
  } | null;
  companion?: {
    name: string;
    pending: boolean;
    onAction: (action: "feed" | "talk" | "care") => void;
  } | null;
  group?: {
    title: string;
    onManage: () => void;
    teamId?: string;
    onOpenTeam?: () => void;
  } | null;
};

type ClusterId = "add-reference" | "conversation-capabilities" | "session-companion" | "group-team";

type Cluster = {
  id: ClusterId;
  label: string;
  icon: ReactNode;
};

function MenuIcon({ children }: { children: ReactNode }) {
  return (
    <span
      data-slot="cluster-icon"
      aria-hidden="true"
      className={styles.clusterIcon}
    >
      {children}
    </span>
  );
}

export function ChatComposerPlusMenu(props: ChatComposerPlusMenuProps) {
  const {
    lang,
    showAddReference = true,
    showCapabilities = true,
    attachmentDisabled,
    onAddAttachments,
    sessionReferences,
    onAddSessionReference,
    mentalModelEnabled,
    runtimeStatusEnabled,
    capabilityDisabled,
    onMentalModelEnabledChange,
    onRuntimeStatusEnabledChange,
    directSession,
    companion,
    group,
  } = props;
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const hoverCloseTimerRef = useRef<number | null>(null);
  const [open, setOpen] = useState(false);
  const [activeCluster, setActiveCluster] = useState<ClusterId | null>(null);
  const [hoverCluster, setHoverCluster] = useState<ClusterId | null>(null);
  const [referenceDialogOpen, setReferenceDialogOpen] = useState(false);
  const [referenceQuery, setReferenceQuery] = useState("");

  const clusters = useMemo<Cluster[]>(() => {
    const items: Cluster[] = [];
    if (showAddReference) {
      items.push({
        id: "add-reference",
        label: lang === "zh" ? "添加与引用" : "Add and reference",
        icon: <ImagePlus size={16} />,
      });
    }
    if (showCapabilities) {
      items.push({
        id: "conversation-capabilities",
        label: lang === "zh" ? "对话能力" : "Conversation capabilities",
        icon: <BrainCircuit size={16} />,
      });
    }
    if (directSession || companion) {
      items.push({
        id: "session-companion",
        label: lang === "zh" ? "会话与陪伴" : "Session and companion",
        icon: <MessageCircleHeart size={16} />,
      });
    }
    if (group) {
      items.push({
        id: "group-team",
        label: lang === "zh" ? "群聊与团队" : "Group and team",
        icon: <UsersRound size={16} />,
      });
    }
    return items;
  }, [companion, directSession, group, lang, showAddReference, showCapabilities]);

  const visibleCluster = hoverCluster ?? activeCluster;
  const filteredReferences = useMemo(() => {
    const query = referenceQuery.trim().toLocaleLowerCase();
    if (!query) {
      return sessionReferences;
    }
    return sessionReferences.filter((option) => `${option.title} ${option.meta ?? ""}`.toLocaleLowerCase().includes(query));
  }, [referenceQuery, sessionReferences]);

  useEffect(() => () => {
    if (hoverCloseTimerRef.current !== null) {
      window.clearTimeout(hoverCloseTimerRef.current);
    }
  }, []);

  function clearHoverCloseTimer() {
    if (hoverCloseTimerRef.current !== null) {
      window.clearTimeout(hoverCloseTimerRef.current);
      hoverCloseTimerRef.current = null;
    }
  }

  function scheduleHoverClose() {
    clearHoverCloseTimer();
    hoverCloseTimerRef.current = window.setTimeout(() => setHoverCluster(null), 160);
  }

  function closeMenu() {
    setOpen(false);
    setActiveCluster(null);
    setHoverCluster(null);
    clearHoverCloseTimer();
  }

  function selectAction(action: () => void) {
    closeMenu();
    action();
  }

  function renderAction(options: {
    id: string;
    label: string;
    hint?: string;
    icon: ReactNode;
    disabled?: boolean;
    onSelect: () => void;
  }) {
    return (
      <VButton
        key={options.id}
        type="button"
        role="menuitem"
        contentLayout="plain"
        variant="ghost"
        className={styles.menuItem}
        isDisabled={options.disabled}
        onPress={() => selectAction(options.onSelect)}
      >
        <span aria-hidden="true" className={styles.itemIcon}>
          {options.icon}
        </span>
        <span className={styles.itemCopy}>
          <strong className={styles.itemLabel}>{options.label}</strong>
          {options.hint ? <small className={styles.itemHint}>{options.hint}</small> : null}
        </span>
      </VButton>
    );
  }

  function renderToggle(options: {
    id: string;
    label: string;
    hint: string;
    icon: ReactNode;
    checked: boolean;
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
        contentLayout="plain"
        variant="ghost"
        className={styles.menuItem}
        isDisabled={capabilityDisabled}
        onPress={() => options.onChange(!options.checked)}
      >
        <span aria-hidden="true" className={styles.itemIcon}>
          {options.icon}
        </span>
        <span className={styles.itemCopy}>
          <strong className={styles.itemLabel}>{options.label}</strong>
          <small className={styles.itemHint}>{options.hint}</small>
        </span>
        <span className={options.checked ? styles.toggleStateOn : styles.toggleStateOff}>
          {stateLabel}
        </span>
      </VButton>
    );
  }

  function renderSecondaryPanel() {
    if (visibleCluster === "add-reference") {
      return (
        <>
          {renderAction({
            id: "attach-image",
            label: lang === "zh" ? "图片附件" : "Image attachment",
            hint: lang === "zh" ? "选择 PNG、JPEG 或 WebP" : "Choose PNG, JPEG, or WebP",
            icon: <ImagePlus size={16} />,
            disabled: attachmentDisabled || !onAddAttachments,
            onSelect: () => attachmentInputRef.current?.click(),
          })}
          {renderAction({
            id: "reference-session",
            label: lang === "zh" ? "引用会话" : "Reference session",
            hint: lang === "zh" ? "选择历史会话加入本轮" : "Attach a previous session to this turn",
            icon: <MessageSquare size={16} />,
            disabled: !onAddSessionReference || sessionReferences.length === 0,
            onSelect: () => {
              setReferenceQuery("");
              setReferenceDialogOpen(true);
            },
          })}
        </>
      );
    }
    if (visibleCluster === "conversation-capabilities") {
      return (
        <>
          {renderToggle({
            id: "mental-model",
            label: lang === "zh" ? "心智模型" : "Mental model",
            hint: lang === "zh" ? "下轮生效" : "Applies next turn",
            icon: <BrainCircuit size={16} />,
            checked: mentalModelEnabled,
            onChange: onMentalModelEnabledChange,
          })}
          {renderToggle({
            id: "runtime-status",
            label: lang === "zh" ? "运行状态注入" : "Runtime status injection",
            hint: lang === "zh" ? "把预算与进度注入上下文" : "Inject budget and progress into context",
            icon: <Activity size={16} />,
            checked: runtimeStatusEnabled,
            onChange: onRuntimeStatusEnabledChange,
          })}
        </>
      );
    }
    if (visibleCluster === "session-companion") {
      return (
        <>
          {directSession ? renderAction({
            id: "open-direct-session",
            label: lang === "zh" ? "打开直接会话" : "Open direct session",
            hint: directSession.label,
            icon: <ArrowUpRight size={16} />,
            onSelect: directSession.onOpen,
          }) : null}
          {companion ? renderAction({
            id: "companion-feed",
            label: lang === "zh" ? "陪伴投喂" : "Feed companion",
            hint: companion.name,
            icon: <Apple size={16} />,
            disabled: companion.pending,
            onSelect: () => companion.onAction("feed"),
          }) : null}
          {companion ? renderAction({
            id: "companion-talk",
            label: lang === "zh" ? "陪伴聊天" : "Talk with companion",
            hint: companion.name,
            icon: <MessageCircleHeart size={16} />,
            disabled: companion.pending,
            onSelect: () => companion.onAction("talk"),
          }) : null}
          {companion ? renderAction({
            id: "companion-care",
            label: lang === "zh" ? "陪伴关怀" : "Care for companion",
            hint: companion.name,
            icon: <HeartHandshake size={16} />,
            disabled: companion.pending,
            onSelect: () => companion.onAction("care"),
          }) : null}
        </>
      );
    }
    if (visibleCluster === "group-team" && group) {
      return (
        <>
          {renderAction({
            id: "manage-group",
            label: lang === "zh" ? "管理群聊" : "Manage group",
            hint: group.title,
            icon: <Settings2 size={16} />,
            onSelect: group.onManage,
          })}
          {group.teamId && group.onOpenTeam ? renderAction({
            id: "open-team",
            label: lang === "zh" ? "打开团队" : "Open team",
            hint: group.teamId,
            icon: <UsersRound size={16} />,
            onSelect: group.onOpenTeam,
          }) : null}
        </>
      );
    }
    return null;
  }

  return (
    <>
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          if (!nextOpen) {
            setActiveCluster(null);
            setHoverCluster(null);
            clearHoverCloseTimer();
          }
        }}
        side="top"
        align="start"
        sideOffset={8}
        aria-label={lang === "zh" ? "更多操作" : "More actions"}
        contentClassName={styles.popoverContent}
        trigger={(
          <VButton
            type="button"
            isIconOnly
            variant="secondary"
            aria-label={lang === "zh" ? "更多操作" : "More actions"}
            icon={<Plus size={16} />}
          />
        )}
      >
        <div
          className={styles.menu}
          role="menu"
          aria-label={lang === "zh" ? "更多操作菜单" : "More actions menu"}
          onPointerLeave={scheduleHoverClose}
        >
          <div className={styles.primaryPanel} data-testid="chat-composer-plus-primary">
            {clusters.map((cluster) => {
              const expanded = cluster.id === visibleCluster;
              return (
                <VButton
                  key={cluster.id}
                  type="button"
                  role="menuitem"
                  aria-haspopup="menu"
                  aria-expanded={expanded}
                  className={expanded ? `${styles.clusterButton} ${styles.clusterButtonExpanded}` : styles.clusterButton}
                  contentLayout="plain"
                  variant="ghost"
                  onPointerEnter={() => {
                    clearHoverCloseTimer();
                    setHoverCluster(cluster.id);
                    cluster.id === "session-companion" && directSession?.onPrefetch?.();
                  }}
                  onPress={() => {
                    setActiveCluster((current) => current === cluster.id ? null : cluster.id);
                    setHoverCluster(cluster.id);
                  }}
                >
                  <MenuIcon>{cluster.icon}</MenuIcon>
                  <strong className={styles.clusterLabel}>{cluster.label}</strong>
                  <ChevronRight size={15} className={styles.clusterChevron} aria-hidden="true" />
                </VButton>
              );
            })}
          </div>
          {visibleCluster ? (
            <div
              className={styles.secondaryPanel}
              role="group"
              aria-label={clusters.find((cluster) => cluster.id === visibleCluster)?.label}
              onPointerEnter={clearHoverCloseTimer}
              onPointerLeave={scheduleHoverClose}
              data-testid="chat-composer-plus-secondary"
            >
              {renderSecondaryPanel()}
            </div>
          ) : null}
        </div>
      </VPopover>

      <VNativeInput
        ref={attachmentInputRef}
        className={styles.hiddenInput}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        disabled={attachmentDisabled}
        aria-label={lang === "zh" ? "选择图片附件" : "Choose image attachments"}
        onChange={(event) => {
          if (event.currentTarget.files && onAddAttachments) {
            onAddAttachments(event.currentTarget.files);
          }
          event.currentTarget.value = "";
        }}
      />

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
          <div className={styles.referenceList} role="listbox" aria-label={lang === "zh" ? "可引用会话" : "Referenceable sessions"}>
            {filteredReferences.map((option) => (
              <VButton
                key={option.id}
                type="button"
                role="option"
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
        </div>
      </VDialog>
    </>
  );
}
