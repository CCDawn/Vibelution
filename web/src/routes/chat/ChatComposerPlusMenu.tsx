import {
  Activity,
  ArrowUpRight,
  BrainCircuit,
  Check,
  ImagePlus,
  MessageCircleHeart,
  MessageSquare,
  Plus,
  Settings2,
  Sparkles,
  UsersRound,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

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
  promptSuggestionEnabled: boolean;
  capabilityDisabled: boolean;
  onMentalModelEnabledChange: (enabled: boolean) => void;
  onRuntimeStatusEnabledChange: (enabled: boolean) => void;
  onPromptSuggestionEnabledChange: (enabled: boolean) => void;
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
    promptSuggestionEnabled,
    capabilityDisabled,
    onMentalModelEnabledChange,
    onRuntimeStatusEnabledChange,
    onPromptSuggestionEnabledChange,
    directSession,
    group,
  } = props;
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [referenceDialogOpen, setReferenceDialogOpen] = useState(false);
  const [referenceQuery, setReferenceQuery] = useState("");

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
    return sessionReferences.filter((option) => `${option.title} ${option.meta ?? ""}`.toLocaleLowerCase().includes(query));
  }, [referenceQuery, sessionReferences]);

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
    onSelect: () => void;
  }) {
    return (
      <VButton
        key={options.id}
        type="button"
        role="menuitem"
        data-plus-menu-item="true"
        className={styles.menuItem}
        contentLayout="plain"
        variant="ghost"
        isDisabled={options.disabled}
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
        className={options.checked ? `${styles.menuItem} ${styles.menuItemChecked}` : styles.menuItem}
        contentLayout="plain"
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

  const attachmentUnavailableReason = lang === "zh" ? "当前会话暂不可添加图片" : "Image attachment is unavailable in this session";
  const referenceUnavailableReason = lang === "zh" ? "没有可引用的历史会话" : "No previous session is available to reference";

  return (
    <>
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
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
          ref={menuRef}
          className={styles.menu}
          role="menu"
          aria-label={lang === "zh" ? "更多操作菜单" : "More actions menu"}
          onKeyDown={handleMenuKeyDown}
        >
          {showAddReference ? renderSection(addReferenceSection, (
            <>
              {renderAction({
                id: "attach-image",
                label: lang === "zh" ? "图片附件" : "Image attachment",
                icon: <ImagePlus size={16} />,
                disabled: attachmentDisabled || !onAddAttachments,
                disabledReason: attachmentUnavailableReason,
                onSelect: () => attachmentInputRef.current?.click(),
              })}
              {renderAction({
                id: "reference-session",
                label: lang === "zh" ? "引用会话" : "Reference session",
                icon: <MessageSquare size={16} />,
                disabled: !onAddSessionReference || sessionReferences.length === 0,
                disabledReason: referenceUnavailableReason,
                onSelect: () => {
                  setReferenceQuery("");
                  setReferenceDialogOpen(true);
                },
              })}
            </>
          )) : null}
          {showCapabilities ? renderSection(capabilitiesSection, (
            <>
              {renderToggle({
                id: "mental-model",
                label: lang === "zh" ? "心智模型" : "Mental model",
                hint: lang === "zh" ? "下轮生效" : "Applies next turn",
                icon: <BrainCircuit size={16} />,
                checked: mentalModelEnabled,
                disabled: capabilityDisabled,
                onChange: onMentalModelEnabledChange,
              })}
              {renderToggle({
                id: "runtime-status",
                label: lang === "zh" ? "运行状态注入" : "Runtime status injection",
                hint: lang === "zh" ? "把预算与进度注入上下文" : "Inject budget and progress into context",
                icon: <Activity size={16} />,
                checked: runtimeStatusEnabled,
                disabled: capabilityDisabled,
                onChange: onRuntimeStatusEnabledChange,
              })}
              {renderToggle({
                id: "prompt-suggestion",
                label: lang === "zh" ? "输入建议" : "Prompt suggestions",
                hint: lang === "zh" ? "回答后提示下一句，Tab 补全" : "Suggests the next prompt after a reply, Tab to complete",
                icon: <Sparkles size={16} />,
                checked: promptSuggestionEnabled,
                disabled: capabilityDisabled,
                onChange: onPromptSuggestionEnabledChange,
              })}
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
