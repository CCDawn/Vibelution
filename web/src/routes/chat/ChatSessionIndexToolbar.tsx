import { Archive, ArrowLeft, ChevronDown, Ellipsis, PanelLeftClose, Plus, Search } from "lucide-react";
import { useId, type Ref } from "react";
import { VButton, VCheckbox, VDropdownMenu, VIconButton, VNativeInput, VPopover, type VDropdownMenuItem } from "../../components/vui";
import type { SessionListPreferences } from "./sessionListPreferences";
import styles from "./ChatSessionIndexToolbar.styles";

export type ChatSessionIndexToolbarProps = {
  lang: "zh" | "en";
  archived: boolean;
  preferences: SessionListPreferences;
  onPreferencesChange: (patch: Partial<SessionListPreferences>) => void;
  onToggleArchive: () => void;
  onSearch: () => void;
  onCollapse: () => void;
  createItems: VDropdownMenuItem[];
  createOpen: boolean;
  onCreateOpenChange: (open: boolean) => void;
  createButtonRef?: Ref<HTMLButtonElement>;
  optionsOpen: boolean;
  onOptionsOpenChange: (open: boolean) => void;
};

export function ChatSessionIndexToolbar({ lang, archived, preferences, onPreferencesChange, onToggleArchive,
  onSearch, onCollapse, createItems, createOpen, onCreateOpenChange, createButtonRef, optionsOpen,
  onOptionsOpenChange }: ChatSessionIndexToolbarProps) {
  const zh = lang === "zh";
  const sortId = useId();
  return <div className={styles.root} data-vui="chat-session-index-toolbar">
    <h2 className={styles.title}>{archived ? (zh ? "已归档" : "Archived") : (zh ? "会话" : "Chats")}</h2>
    {archived ? <VButton variant="ghost" className={styles.back} icon={<ArrowLeft size={16} aria-hidden="true" />}
      onPress={onToggleArchive} aria-label={zh ? "返回会话" : "Back to chats"}>{zh ? "返回" : "Back"}</VButton> :
      <VDropdownMenu aria-label={zh ? "新建" : "Create"} align="start" open={createOpen} onOpenChange={onCreateOpenChange}
        items={createItems} trigger={<VButton ref={createButtonRef} id="chat-agent-create-trigger" variant="primary"
          className={styles.create} aria-label={zh ? "新建" : "Create"} aria-keyshortcuts="Control+N Meta+N"
          title={zh ? "新建（Ctrl+N）" : "Create (Ctrl+N)"} icon={<Plus size={16} aria-hidden="true" />}
          trailingIcon={<ChevronDown size={14} aria-hidden="true" />}>{zh ? "新建" : "New"}</VButton>} />}
    <VIconButton className={styles.icon} tooltip="" label={zh ? "搜索会话、Agent 或团队" : "Search chats, Agents or teams"}
      title={zh ? "搜索（Ctrl+K）" : "Search (Ctrl+K)"} data-vui="session-catalog-entry"
      aria-keyshortcuts="Control+K Meta+K" icon={<Search size={16} aria-hidden="true" />} onClick={onSearch} />
    <VPopover open={optionsOpen} onOpenChange={onOptionsOpenChange} align="end"
      aria-label={zh ? "更多与显示选项" : "More and display options"} contentClassName={styles.options}
      data-vui="chat-session-display-options" trigger={<VIconButton tooltip="" className={styles.icon}
        label={zh ? "更多与显示选项" : "More and display options"} icon={<Ellipsis size={16} aria-hidden="true" />} />}>
      <VButton variant="ghost" className={styles.archive} data-vui="session-archive-toggle" aria-pressed={archived}
        icon={<Archive size={16} aria-hidden="true" />} onPress={() => { onOptionsOpenChange(false); onToggleArchive(); }}>
        {archived ? (zh ? "返回会话" : "Back to chats") : (zh ? "查看已归档" : "View archived")}
      </VButton>
      <div className={styles.divider} />
      <div className={styles.optionLabel} id={sortId}>{zh ? "排序方式" : "Sort by"}</div>
      <div role="radiogroup" aria-labelledby={sortId}>
        {(["updatedAt", "createdAt"] as const).map(value => <label key={value} className={styles.radio}>
          <VNativeInput type="radio" name={sortId} value={value} checked={preferences.sortBy === value}
            onChange={() => onPreferencesChange({ sortBy: value })} />
          {value === "updatedAt" ? (zh ? "最近更新优先" : "Recently updated") : (zh ? "最近创建优先" : "Recently created")}
        </label>)}
      </div>
      {archived ? null : <><div className={styles.divider} /><VCheckbox className={styles.grouping}
        data-vui="chat-session-timeline-toggle" isSelected={preferences.timelineGrouping}
        onChange={timelineGrouping => onPreferencesChange({ timelineGrouping })}>{zh ? "按日期分组" : "Group by date"}</VCheckbox></>}
    </VPopover>
    <VIconButton tooltip="" id="chat-conversation-index-collapse" className={`${styles.icon} ${styles.collapse}`}
      label={zh ? "收起会话列" : "Collapse conversation column"} aria-expanded={true} aria-controls="chat-conversation-index-pane"
      icon={<PanelLeftClose size={16} aria-hidden="true" />} onClick={onCollapse} />
  </div>;
}
