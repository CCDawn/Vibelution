import { useEffect, useMemo, useState } from "react";
import { Activity, BrainCircuit, BookOpen, FolderGit2, Users, X } from "lucide-react";

import {
  VButton,
  VCheckbox,
  VChip,
  VInput,
  VNativeSelect,
  VSection,
  VSettingsGroupCard,
  VSettingsRow,
  VStateSurface,
  VSwitch,
  VSplitWorkspace,
  VTabs,
} from "../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import panelStyles from "./AgentPerceptionPanel.styles";
import {
  setKnowledgeBaseScope,
  setPerceptionSourceMode,
  setPerceptionTrigger,
  toggleExcludedKnowledgeBase,
  togglePerceptionScopeId,
  validateAgentPerceptionPolicy,
} from "./agentPerceptionDraft";
import { useAgentPerceptionDraft, type AgentPerceptionDraftStore } from "./useAgentPerceptionDraft";
import type {
  AgentPerceptionConfiguration,
  AgentPerceptionMode,
  AgentPerceptionNotification,
  AgentPerceptionPolicy,
  AgentPerceptionRuntime,
  AgentPerceptionScopeOption,
  AgentPerceptionSourceId,
  AgentPerceptionTriggerId,
} from "./types";

type AgentPerceptionPanelProps = {
  agentId: string;
  lang: "zh" | "en";
  configuration: AgentPerceptionConfiguration | null;
  configurationPending: boolean;
  configurationError?: string | null;
  onRetryConfiguration: () => void;
  runtime: AgentPerceptionRuntime | null;
  runtimePending: boolean;
  runtimeError?: string | null;
  onRetryRuntime: () => void;
  savePending: boolean;
  saveError?: string | null;
  onSave: (policy: AgentPerceptionPolicy, expectedAgentUpdatedAt: string) => void;
  onOpenSession: (sessionId: string) => void;
  draftStore?: AgentPerceptionDraftStore;
  cancelPending: boolean;
  cancelError?: string | null;
  onCancelRun: (runId: string) => void;
};

type Copy = {
  title: string; description: string; enabled: string; enabledHint: string;
  settingsTab: string; historyTab: string; historyHint: string;
  configured: string; notConfigured: string; legacyHint: string; disabledHint: string;
  save: string; discard: string; saved: string; dirty: string;
  revisionConflictTitle: string; revisionConflictMessage: string; reloadLatest: string;
  sourceTitle: string; sourceHint: string; mode: string; modeOff: string; modeManual: string; modeAuto: string;
  personal: string; personalHint: string; team: string; teamHint: string; knowledge: string; knowledgeHint: string;
  projects: string; projectsHint: string; teamsEmpty: string; basesEmpty: string; selected: string; allAuthorized: string;
  unknownScope: string; triggerTask: string; triggerUpdate: string; triggerBackground: string; manualRule: string;
  aclHint: string; backgroundTitle: string; backgroundHint: string; backgroundEnabled: string;
  interval: string; intervalHint: string; dailyMaxRuns: string; maxCalls: string; maxInputTokens: string;
  maxResultChars: string; concurrent: string; topics: string; topicsHint: string; topicPlaceholder: string;
  addTopic: string; topicLimit: string; notificationMode: string; notificationsImportant: string;
  notificationsAll: string; notificationsQuiet: string; notificationHint: string;
  runtimeTitle: string; runtimeHint: string; runtimeStatus: string; readableSources: string; actualSources: string;
  noReadableSources: string; lastActivity: string; trigger: string; readCount: string; resultCount: string;
  selectedCount: string; readableCount: string; dailyBudget: string; budgetRemaining: string;
  activeTriggers: string; requiresUserRequest: string;
  activeRun: string; lastRun: string; noRun: string; noSourcesRead: string; cancel: string;
  openResearchSession: string; runFailedHint: string;
  runId: string; startedAt: string; finishedAt: string; toolCalls: string; inputTokens: string;
  outputChars: string; sourceReadCalls: string; nextRun: string; notifications: string; unread: string; suppressed: string;
  noNotifications: string; knowledgeItem: string; revision: string; observedAt: string;
  relatedResult: string; newUpdate: string; openSession: string; knowledgeBaseId: string; loadFailed: string; retry: string;
  invalidPolicy: string; savedHint: string; notGranted: string; usage: string; remove: string;
};

function copyFor(lang: "zh" | "en"): Copy {
  return lang === "zh"
    ? {
        title: "感知管理",
        description: "设定 Agent 可主动查询的个人、团队、知识库和本地成熟项目索引范围。",
        enabled: "启用感知控制",
        enabledHint: "关闭后停止新的感知读取；已有会话内容不会被清除，也不会更改知识或工具权限。",
        settingsTab: "感知设置", historyTab: "运行记录", historyHint: "这里只显示服务端记录的实际运行、读取和更新通知。",
        configured: "已保存策略",
        notConfigured: "尚未保存策略",
        legacyHint: "首次保存前继续采用 Agent 现有行为；保存后才开始执行这里的感知边界。",
        disabledHint: "当前策略关闭。保存后会显式阻止新的感知读取。",
        save: "保存策略", discard: "放弃未保存修改", saved: "策略已保存", dirty: "有未保存修改",
        revisionConflictTitle: "策略已在其他位置更新",
        revisionConflictMessage: "当前草稿基于旧版本；为避免覆盖最新设置，保存已暂停。重新加载会丢弃本地未保存修改。",
        reloadLatest: "加载最新策略",
        sourceTitle: "可感知来源",
        sourceHint: "每个来源分别设定关闭、按需查询或自动感知。自动读取仍逐次受当前读取权限、记忆策略和工具策略约束。",
        mode: "感知方式", modeOff: "关闭", modeManual: "按需查询", modeAuto: "自动感知",
        personal: "个人记忆与私有知识库",
        personalHint: "读取该 Agent 的个人记忆与正式私有知识库；个人记忆保存权限仍单独控制。",
        team: "指定团队", teamHint: "只从选中的团队读取；列表按当前读取权限和 Agent 的记忆策略筛选。",
        knowledge: "授权知识库", knowledgeHint: "只列出当前可读的共享知识库；同名库会按所属 Agent 或团队区分。",
        projects: "本地成熟项目索引",
        projectsHint: "使用本地项目治理卡片索引；本设置只控制知识读取，通用文件和命令权限仍由工具策略独立控制。",
        teamsEmpty: "当前没有可配置的可读团队。", basesEmpty: "当前读取权限内没有可配置的共享知识库。",
        selected: "仅选定知识库", allAuthorized: "全部当前可读知识库", unknownScope: "已保存的范围当前不可读，保留设置但不会放宽访问。",
        triggerTask: "任务触发时", triggerUpdate: "知识更新时", triggerBackground: "后台计划时",
        manualRule: "仅当用户在本轮明确要求查询时才读取；Agent 自称获得授权不算用户请求。",
        aclHint: "策略限定 Agent 的自动读取范围，不会授予团队、知识库或工具权限。",
        backgroundTitle: "后台调研与通知",
        backgroundHint: "后台调研仅按你定义的主题和用量上限运行；每个 Agent 最多并发一个任务。",
        backgroundEnabled: "启用后台调研", interval: "检查间隔（分钟）", intervalHint: "15–10,080 分钟",
        dailyMaxRuns: "每日最多运行次数", maxCalls: "每次最多工具调用", maxInputTokens: "每次最多输入 token",
        maxResultChars: "每次最多结果字符数", concurrent: "最大并发", topics: "调研主题",
        topicsHint: "只依据这些明确主题运行；最多 8 个，每个不超过 200 字。",
        topicPlaceholder: "添加一个调研主题", addTopic: "添加主题", topicLimit: "最多添加 8 个主题。",
        notificationMode: "通知策略", notificationsImportant: "仅重要更新", notificationsAll: "全部更新",
        notificationsQuiet: "静音通知", notificationHint: "仅重要更新按已配置的调研主题筛选；未配置主题时可选择“全部更新”。静音只控制通知，不关闭更新扫描；关闭后台调研也不会停止更新扫描。",
        runtimeTitle: "运行状态与实际读取",
        runtimeHint: "列出的来源仅表示策略和当前读取权限允许；本轮实际执行仍须通过本轮工具授权，实际读取只依据执行记录。",
        runtimeStatus: "后台调研状态", readableSources: "当前来源范围", actualSources: "实际读取来源",
        noReadableSources: "当前没有可用来源。",
        lastActivity: "最近一次实际读取", trigger: "触发方式", readCount: "读取次数", resultCount: "返回条目",
        selectedCount: "策略命中",
        readableCount: "权限复核后可读", dailyBudget: "今日后台额度", budgetRemaining: "剩余",
        activeTriggers: "生效触发器", requiresUserRequest: "需本轮用户明确请求",
        activeRun: "正在运行", lastRun: "最近一次运行", noRun: "尚无读取记录",
        noSourcesRead: "这次运行还没有已记录的读取来源。", cancel: "停止后台调研",
        openResearchSession: "查看调研会话", runFailedHint: "本次后台调研失败；可打开关联会话查看执行记录。",
        runId: "运行编号", startedAt: "开始时间", finishedAt: "结束时间", toolCalls: "工具调用",
        inputTokens: "输入 token", outputChars: "结果字符", sourceReadCalls: "来源读取调用", nextRun: "下次计划",
        notifications: "知识更新通知", unread: "未查看更新", suppressed: "未生成通知的变化", noNotifications: "暂无知识更新通知。",
        knowledgeItem: "知识条目", revision: "版本", observedAt: "发现时间", relatedResult: "关联任务/结果",
        newUpdate: "新更新", openSession: "打开关联会话", knowledgeBaseId: "知识库 ID",
        loadFailed: "感知数据加载失败", retry: "重试", invalidPolicy: "策略参数不符合允许的范围。",
        savedHint: "配置保存后立即作为后续检索的边界。",
        notGranted: "本设置不会更改当前读取权限、通用文件和命令权限、知识写入、审批或个人记忆保存权限。",
        usage: "本次用量", remove: "删除",
      }
    : {
        title: "Perception",
        description: "Choose which personal, team, knowledge-base, and local project sources this Agent may consult.",
        enabled: "Enable perception control",
        enabledHint: "Turning this off stops new perception reads. Existing conversation content and source permissions remain unchanged.",
        settingsTab: "Settings", historyTab: "Run history", historyHint: "Only server-recorded runs, reads, and update notifications appear here.",
        configured: "Policy saved", notConfigured: "Policy not saved",
        legacyHint: "The Agent keeps its existing behavior until a policy is saved.",
        disabledHint: "This policy is off. Saving it explicitly blocks new perception reads.",
        save: "Save policy", discard: "Discard changes", saved: "Policy saved", dirty: "Unsaved changes",
        revisionConflictTitle: "The policy changed elsewhere",
        revisionConflictMessage: "This draft uses an older revision. Saving is paused to avoid overwriting newer settings. Reloading will discard this local draft.",
        reloadLatest: "Load latest policy",
        sourceTitle: "Perception sources",
        sourceHint: "Choose off, on-demand, or automatic perception for each source. Every automatic read is checked against current read access, memory policy, and tool policy.",
        mode: "Perception mode", modeOff: "Off", modeManual: "On demand", modeAuto: "Automatic",
        personal: "Personal memory and private knowledge base",
        personalHint: "Reads this Agent’s personal memory and formal private knowledge base. Permission to save personal memory remains separate.",
        team: "Selected teams", teamHint: "Reads only selected teams. Options are filtered by current read access and this Agent’s memory policy.",
        knowledge: "Authorized knowledge bases", knowledgeHint: "Only shared knowledge bases currently readable to this Agent are listed. Same-named bases stay distinguished by their owning Agent or team.",
        projects: "Local mature-project index", projectsHint: "Uses the local project governance index. This setting controls knowledge reads; general file and command permissions remain governed separately by tool policy.",
        teamsEmpty: "There are no readable teams available to configure.",
        basesEmpty: "No shared knowledge bases currently fall within this Agent’s read access.",
        selected: "Selected knowledge bases only", allAuthorized: "All currently readable knowledge bases",
        unknownScope: "A saved scope is currently unreadable. It is preserved without widening access.",
        triggerTask: "When a task starts", triggerUpdate: "When knowledge changes", triggerBackground: "On the background schedule",
        manualRule: "Read only when the user explicitly asks in this turn. An Agent claiming authorization does not count as a user request.",
        aclHint: "This policy limits automatic reads; it does not grant read access to teams or knowledge bases, or tool permissions.",
        backgroundTitle: "Background research and notifications",
        backgroundHint: "Background research follows your topics and usage caps. Each Agent is limited to one concurrent run.",
        backgroundEnabled: "Enable background research", interval: "Check interval (minutes)", intervalHint: "15–10,080 minutes",
        dailyMaxRuns: "Maximum runs per day", maxCalls: "Maximum tool calls per run",
        maxInputTokens: "Maximum input tokens per run", maxResultChars: "Maximum result characters per run",
        concurrent: "Maximum concurrency", topics: "Research topics",
        topicsHint: "Research only these explicit topics; up to 8, each no longer than 200 characters.",
        topicPlaceholder: "Add a research topic", addTopic: "Add topic", topicLimit: "Up to 8 topics.",
        notificationMode: "Notification policy", notificationsImportant: "Important updates only",
        notificationsAll: "All updates", notificationsQuiet: "Quiet notifications",
        notificationHint: "Important updates are filtered by configured research topics; choose All updates when no topics are configured. Quiet mode only affects notifications, and disabling background research does not stop update scanning.",
        runtimeTitle: "Runtime and actual reads",
        runtimeHint: "Listed sources only reflect policy and current read access. Each run must still pass this turn's tool authorization; actual reads are based only on execution records.",
        runtimeStatus: "Background research status", readableSources: "Current source scope",
        actualSources: "Sources actually read",
        noReadableSources: "No sources are currently available.", lastActivity: "Most recent actual reads",
        trigger: "Trigger", readCount: "Read count", resultCount: "Results",
        selectedCount: "Policy matched",
        readableCount: "Readable after permission checks", dailyBudget: "Today's background budget",
        activeTriggers: "Active triggers", requiresUserRequest: "Requires an explicit request in this turn",
        budgetRemaining: "Remaining", activeRun: "Running now", lastRun: "Last run", noRun: "No read recorded yet",
        noSourcesRead: "This run has no recorded source reads yet.", cancel: "Stop background research",
        openResearchSession: "View research session", runFailedHint: "This background research run failed. Open its native session to inspect the execution record.",
        runId: "Run ID", startedAt: "Started", finishedAt: "Finished", toolCalls: "Tool calls",
        inputTokens: "Input tokens", outputChars: "Result characters", sourceReadCalls: "Source-read calls", nextRun: "Next scheduled run",
        notifications: "Knowledge update notifications", unread: "New updates", suppressed: "Changes without a notification",
        noNotifications: "There are no knowledge update notifications.",
        knowledgeItem: "Knowledge item", revision: "Revision", observedAt: "Observed", relatedResult: "Related task/result",
        newUpdate: "New update", openSession: "Open related session", knowledgeBaseId: "Knowledge base ID",
        loadFailed: "Could not load perception data", retry: "Retry",
        invalidPolicy: "One or more policy values are outside the allowed range.",
        savedHint: "The saved policy applies to future perception requests.",
        notGranted: "This setting does not change current read access, general file or command permissions, knowledge writes, approvals, or personal-memory saving.",
        usage: "Usage", remove: "Remove",
      };
}

const SOURCE_IDS: AgentPerceptionSourceId[] = ["personal", "team", "knowledge", "projects"];
const TRIGGER_IDS: AgentPerceptionTriggerId[] = ["task", "update", "background"];
const langText = (lang: "zh" | "en", zh: string, en: string) => lang === "zh" ? zh : en;

function sourceIcon(source: AgentPerceptionSourceId) {
  switch (source) {
    case "personal": return <BrainCircuit size={16} aria-hidden="true" />;
    case "team": return <Users size={16} aria-hidden="true" />;
    case "knowledge": return <BookOpen size={16} aria-hidden="true" />;
    case "projects": return <FolderGit2 size={16} aria-hidden="true" />;
  }
}

function readableTime(value: string | null | undefined, lang: "zh" | "en") {
  if (!value) return "—";
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? value : time.toLocaleString(lang === "zh" ? "zh-CN" : "en-US");
}

function statusLabel(value: string, lang: "zh" | "en") {
  const labels: Record<string, { zh: string; en: string }> = {
    idle: { zh: "空闲", en: "Idle" }, disabled: { zh: "已关闭", en: "Disabled" },
    scheduled: { zh: "已计划", en: "Scheduled" }, running: { zh: "运行中", en: "Running" },
    queued: { zh: "排队中", en: "Queued" }, stopping: { zh: "正在停止", en: "Stopping" },
    cancelled: { zh: "已停止", en: "Stopped" }, completed: { zh: "已完成", en: "Completed" },
    failed: { zh: "失败", en: "Failed" }, interrupted: { zh: "已中断", en: "Interrupted" },
    degraded: { zh: "部分不可用", en: "Degraded" },
    blocked: { zh: "被权限拦截", en: "Blocked by access policy" },
  };
  return labels[value]?.[lang] ?? value;
}

function OptionList({
  options, selectedIds, onToggle, emptyLabel, unknownLabel,
}: {
  options: AgentPerceptionScopeOption[];
  selectedIds: string[];
  onToggle: (id: string, selected: boolean) => void;
  emptyLabel: string;
  unknownLabel: string;
}) {
  const availableIds = new Set(options.map((option) => option.id));
  const missingIds = selectedIds.filter((id) => !availableIds.has(id));
  if (!options.length && !missingIds.length) {
    return <VStateSurface className={panelStyles.scopeEmpty} density="compact" tone="empty" title={emptyLabel} data-testid="perception-scope-empty" />;
  }
  const renderOption = (id: string, label: string, detail: string | undefined, selected: boolean, missing = false) => (
    <VCheckbox
      key={id}
      isSelected={selected}
      onChange={(next) => onToggle(id, next)}
      aria-label={label}
      className={panelStyles.scopeOption}
    >
      <span className={panelStyles.scopeOptionBody}>
        <span className={panelStyles.scopeOptionTitle}>{label}</span>
        {detail || missing ? <span className={panelStyles.scopeOptionDetail}>{missing ? unknownLabel : detail}</span> : null}
      </span>
    </VCheckbox>
  );
  return (
    <div className={panelStyles.scopeOptions} data-testid="perception-scope-options">
      {options.map((option) => renderOption(option.id, option.label, option.detail, selectedIds.includes(option.id)))}
      {missingIds.map((id) => renderOption(id, id, undefined, true, true))}
    </div>
  );
}

function SourceCard({
  copy, lang, source, policy, options, updatePolicy,
}: {
  copy: Copy;
  lang: "zh" | "en";
  source: AgentPerceptionSourceId;
  policy: AgentPerceptionPolicy;
  options?: AgentPerceptionScopeOption[];
  updatePolicy: (updater: (current: AgentPerceptionPolicy) => AgentPerceptionPolicy) => void;
}) {
  const sourcePolicy = policy.sources[source];
  const label = source === "personal" ? copy.personal
    : source === "team" ? copy.team
      : source === "knowledge" ? copy.knowledge : copy.projects;
  const hint = source === "personal" ? copy.personalHint
    : source === "team" ? copy.teamHint
      : source === "knowledge" ? copy.knowledgeHint : copy.projectsHint;
  const updateScope = (id: string, selected: boolean) => {
    if (source === "team" || source === "knowledge") {
      updatePolicy((current) => togglePerceptionScopeId(current, source, id, selected));
    }
  };
  const modeOptions = [
    { id: "off", label: copy.modeOff },
    { id: "manual", label: copy.modeManual },
    { id: "auto", label: copy.modeAuto },
  ];
  return (
    <VSettingsGroupCard className={panelStyles.minWidthZero} data-testid={"perception-source-" + source}>
      <div className={panelStyles.sourceHeading}>
        <span className={panelStyles.sourceIcon}>
          {sourceIcon(source)}
        </span>
        <div className={panelStyles.minWidthZero}>
          <h3 className={panelStyles.sourceTitle}>{label}</h3>
          <p className={panelStyles.sourceHint}>{hint}</p>
        </div>
      </div>
      <VSettingsRow
        label={copy.mode}
        control={(
          <VNativeSelect
            aria-label={label + " · " + copy.mode}
            value={sourcePolicy.mode}
            onChange={(event) => updatePolicy((current) => setPerceptionSourceMode(current, source, event.currentTarget.value as AgentPerceptionMode))}
          >
            {modeOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
          </VNativeSelect>
        )}
        detail={sourcePolicy.mode === "manual"
          ? <p className={panelStyles.ruleText}>{copy.manualRule}</p>
          : sourcePolicy.mode === "auto"
            ? <p className={panelStyles.ruleText}>{copy.aclHint}</p>
            : undefined}
      />
      {sourcePolicy.mode === "auto" ? (
        <VSettingsRow
          label={langText(lang, "自动触发条件", "Automatic triggers")}
          description={langText(lang, "按任务、知识更新和后台计划分别启停。", "Control task, knowledge-update, and scheduled triggers separately.")}
          footer={(
            <div className={panelStyles.triggerList}>
              {TRIGGER_IDS.map((trigger) => (
                <VCheckbox
                  key={trigger}
                  isSelected={sourcePolicy.triggers[trigger]}
                  onChange={(enabled) => updatePolicy((current) => setPerceptionTrigger(current, source, trigger, enabled))}
                >
                  {trigger === "task" ? copy.triggerTask : trigger === "update" ? copy.triggerUpdate : copy.triggerBackground}
                </VCheckbox>
              ))}
            </div>
          )}
        />
      ) : null}
      {source === "team" ? (
        <VSettingsRow
          label={langText(lang, "团队范围", "Team scope")}
          footer={(
            <OptionList
              options={options ?? []}
              selectedIds={policy.sources.team.teamIds}
              onToggle={updateScope}
              emptyLabel={copy.teamsEmpty}
              unknownLabel={copy.unknownScope}
            />
          )}
        />
      ) : null}
      {source === "knowledge" ? (
        <>
          <VSettingsRow
            label={langText(lang, "知识库范围", "Knowledge-base scope")}
            control={(
              <VNativeSelect
                aria-label={langText(lang, "知识库范围", "Knowledge-base scope")}
                value={policy.sources.knowledge.scope}
                onChange={(event) => updatePolicy((current) => setKnowledgeBaseScope(current, event.currentTarget.value as "selected" | "all_authorized"))}
              >
                <option value="selected">{copy.selected}</option>
                <option value="all_authorized">{copy.allAuthorized}</option>
              </VNativeSelect>
            )}
          />
          <VSettingsRow
            label={policy.sources.knowledge.scope === "selected" ? copy.selected : copy.allAuthorized}
            description={policy.sources.knowledge.scope === "selected"
              ? langText(lang, "仅从已勾选的知识库读取。", "Read only from checked knowledge bases.")
              : langText(lang, "读取仍限制在当前读取权限和 Agent 记忆策略可读范围内。", "Reads remain limited by current read access and this Agent’s memory policy.")}
            footer={(
              <OptionList
                options={options ?? []}
                selectedIds={policy.sources.knowledge.scope === "selected"
                  ? policy.sources.knowledge.knowledgeBaseIds
                  : policy.sources.knowledge.excludedKnowledgeBaseIds}
                onToggle={(id, selected) => policy.sources.knowledge.scope === "selected"
                  ? updateScope(id, selected)
                  : updatePolicy((current) => toggleExcludedKnowledgeBase(current, id, selected))}
                emptyLabel={copy.basesEmpty}
                unknownLabel={copy.unknownScope}
              />
            )}
          />
        </>
      ) : null}
    </VSettingsGroupCard>
  );
}

function NumberSetting({
  id, label, description, value, min, max, onChange,
}: {
  id: string;
  label: string;
  description?: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <VSettingsRow
      label={<label htmlFor={id}>{label}</label>}
      description={description}
      control={(
        <VInput
          id={id}
          aria-label={label}
          type="number"
          min={min}
          max={max}
          step={1}
          value={Number.isFinite(value) ? value : ""}
          onChange={(event) => onChange(event.currentTarget.value === "" ? Number.NaN : event.currentTarget.valueAsNumber)}
        />
      )}
    />
  );
}

function TopicEditor({ topics, copy, onChange }: { topics: string[]; copy: Copy; onChange: (next: string[]) => void }) {
  const [topic, setTopic] = useState("");
  const normalizedTopic = topic.trim().replace(/\s+/g, " ");
  const canAdd = Boolean(normalizedTopic) && normalizedTopic.length <= 200 && !topics.includes(normalizedTopic) && topics.length < 8;
  return (
    <VSettingsRow
      label={copy.topics}
      description={copy.topicsHint}
      footer={(
        <div className={panelStyles.sectionStack}>
          <div className={panelStyles.inlineControls}>
            <VInput
              aria-label={copy.topicPlaceholder}
              value={topic}
              maxLength={200}
              placeholder={copy.topicPlaceholder}
              onChange={(event) => setTopic(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && canAdd) {
                  event.preventDefault();
                  onChange([...topics, normalizedTopic]);
                  setTopic("");
                }
              }}
              className={panelStyles.topicInput}
            />
            <VButton type="button" isDisabled={!canAdd} onPress={() => { onChange([...topics, normalizedTopic]); setTopic(""); }}>
              {copy.addTopic}
            </VButton>
          </div>
          {topics.length >= 8 ? <p className={panelStyles.hintText}>{copy.topicLimit}</p> : null}
          {topics.length ? (
            <ul className={panelStyles.topicList} aria-label={copy.topics}>
              {topics.map((value) => (
                <li key={value} className={panelStyles.listItem}>
                  <VChip className={panelStyles.topicChip}>
                    <span className={panelStyles.topicText}>{value}</span>
                    <VButton
                      type="button"
                      variant="ghost"
                      density="compact"
                      isIconOnly
                      aria-label={value + " · " + copy.remove}
                      onPress={() => onChange(topics.filter((item) => item !== value))}
                    >
                      <X size={12} aria-hidden="true" />
                    </VButton>
                  </VChip>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    />
  );
}

function RunUsage({
  run, copy, lang, label, sourceNames, onOpenSession,
}: {
  run: NonNullable<AgentPerceptionRuntime["lastRun"]>;
  copy: Copy;
  lang: "zh" | "en";
  label: string;
  sourceNames: Record<AgentPerceptionSourceId, string>;
  onOpenSession: (sessionId: string) => void;
}) {
  return (
    <VSettingsGroupCard className={panelStyles.minWidthZero} data-testid="perception-run">
      <div className={panelStyles.cardHeading}>
        <strong className={panelStyles.cardTitle}>{label}</strong>
        <div className={panelStyles.inlineControls}>
          <VChip>{statusLabel(run.status, lang)}</VChip>
          {run.sessionId ? (
            <VButton
              type="button"
              variant="ghost"
              density="compact"
              aria-label={`${copy.openResearchSession}: ${run.sessionId}`}
              onPress={() => onOpenSession(run.sessionId)}
            >
              {copy.openResearchSession}
            </VButton>
          ) : null}
        </div>
      </div>
      {run.status === "failed" ? <p className={panelStyles.runFailureHint}>{copy.runFailedHint}</p> : null}
      <VSettingsRow label={copy.runId} detail={<code className={panelStyles.runIdentifier}>{run.runId}</code>} />
      <VSettingsRow label={copy.startedAt} detail={<span className={panelStyles.smallText}>{readableTime(run.startedAt, lang)}</span>} />
      {run.finishedAt ? <VSettingsRow label={copy.finishedAt} detail={<span className={panelStyles.smallText}>{readableTime(run.finishedAt, lang)}</span>} /> : null}
      {run.sources?.length ? (
        <VSettingsRow
          label={copy.actualSources}
          detail={<span className={panelStyles.detailText}>{run.sources.map((source) => sourceNames[source]).join("、")}</span>}
        />
      ) : null}
      <VSettingsRow
        label={copy.usage}
        detail={(
          <span className={panelStyles.usageRow}>
            <span>{copy.toolCalls}: {run.toolCallsUsed}</span>
            <span>{copy.sourceReadCalls}: {run.sourceReadCallsUsed}</span>
            <span>{copy.readCount}: {run.readCount}</span>
            <span>{copy.resultCount}: {run.resultCount}</span>
            <span>{copy.inputTokens}: {run.inputTokensUsed}</span>
            <span>{copy.outputChars}: {run.outputCharsUsed}</span>
          </span>
        )}
      />
    </VSettingsGroupCard>
  );
}

function NotificationRow({
  item,
  copy,
  lang,
  knowledgeBaseName,
  onOpenSession,
}: {
  item: AgentPerceptionNotification;
  copy: Copy;
  lang: "zh" | "en";
  knowledgeBaseName: string;
  onOpenSession: (sessionId: string) => void;
}) {
  return (
    <li className={panelStyles.updateItem}>
      <div className={panelStyles.rowHeading}>
        <strong className={panelStyles.itemTitle}>{knowledgeBaseName || item.knowledgeBaseId || "—"}</strong>
        {!item.delivered ? <VChip>{copy.newUpdate}</VChip> : null}
      </div>
      <div className={panelStyles.updateDetails}>
        {item.knowledgeBaseId ? <span className={panelStyles.breakAll}>{copy.knowledgeBaseId}: {item.knowledgeBaseId}</span> : null}
        <span className={panelStyles.breakAll}>{copy.knowledgeItem}: {item.knowledgeItemId}</span>
        <span>{copy.revision}: {item.revision}</span>
        <span>{copy.observedAt}: {readableTime(item.observedAt, lang)}</span>
        <span className={panelStyles.updateLinks}>
          {copy.relatedResult}: {item.sessionId ? (
            <>
              <VButton type="button" variant="ghost" density="compact" aria-label={`${copy.openSession}: ${item.sessionId}`} onPress={() => onOpenSession(item.sessionId)}>{copy.openSession}</VButton>
              <code>{item.sessionId}</code>
            </>
          ) : "—"}
          {item.turnId ? <code>{item.turnId}</code> : null}
        </span>
      </div>
      <span className={panelStyles.screenReader}>{item.notificationId} · {item.contentHash} · {item.turnId}</span>
    </li>
  );
}

function RuntimeSummary({
  copy, lang, runtime, pending, error, onRetry,
}: {
  copy: Copy;
  lang: "zh" | "en";
  runtime: AgentPerceptionRuntime | null;
  pending: boolean;
  error?: string | null;
  onRetry: () => void;
}) {
  if (pending && !runtime) {
    return <VStateSurface tone="loading" title={copy.runtimeTitle} skeletonLines={2}>{copy.runtimeHint}</VStateSurface>;
  }
  if (error && !runtime) {
    return <VStateSurface tone="error" title={copy.loadFailed} actions={<VButton type="button" onPress={onRetry}>{copy.retry}</VButton>}>{error}</VStateSurface>;
  }
  if (!runtime) {
    return <VStateSurface tone="empty" title={copy.noRun}>{copy.runtimeHint}</VStateSurface>;
  }

  const sourceNames: Record<AgentPerceptionSourceId, string> = {
    personal: copy.personal,
    team: copy.team,
    knowledge: copy.knowledge,
    projects: copy.projects,
  };
  const latestActualSources = runtime.activeRun?.sources.length
    ? runtime.activeRun.sources
    : runtime.lastActivity?.sources ?? [];

  return (
    <div className={panelStyles.stack} data-testid="perception-runtime-summary">
      <VSection title={copy.runtimeTitle} meta={runtime.updatedAt ? readableTime(runtime.updatedAt, lang) : undefined}>
        {error ? <VStateSurface tone="error" density="compact" title={copy.loadFailed} actions={<VButton type="button" onPress={onRetry}>{copy.retry}</VButton>}>{error}</VStateSurface> : null}
        <VSettingsGroupCard>
          <VSettingsRow
            label={copy.runtimeStatus}
            control={<VChip>{statusLabel(runtime.status, lang)}</VChip>}
            detail={runtime.nextRunAt ? <span className={panelStyles.mutedText}>{copy.nextRun}: {readableTime(runtime.nextRunAt, lang)}</span> : undefined}
          />
          {runtime.activeRun ? (
            <VSettingsRow label={copy.activeRun} control={<VChip>{statusLabel(runtime.activeRun.status, lang)}</VChip>} />
          ) : null}
          <VSettingsRow
            label={copy.readableSources}
            detail={runtime.readableSources.length ? (
              <span className={panelStyles.detailText}>
                {runtime.readableSources.map((source) => `${sourceNames[source.source]} (${source.readableCount})`).join("、")}
              </span>
            ) : <span className={panelStyles.mutedText}>{copy.noReadableSources}</span>}
          />
          <VSettingsRow
            label={copy.lastActivity}
            detail={runtime.lastActivity ? (
              <span className={panelStyles.detailText}>{readableTime(runtime.lastActivity.completedAt, lang)}</span>
            ) : <span className={panelStyles.mutedText}>{copy.noRun}</span>}
          />
          <VSettingsRow
            label={copy.actualSources}
            detail={latestActualSources.length ? (
              <span className={panelStyles.detailText}>{latestActualSources.map((source) => sourceNames[source]).join("、")}</span>
            ) : <span className={panelStyles.mutedText}>{copy.noSourcesRead}</span>}
          />
          <VSettingsRow
            label={copy.usage}
            detail={runtime.lastActivity ? (
              <span className={panelStyles.detailText}>{copy.readCount}: {runtime.lastActivity.readCount} · {copy.resultCount}: {runtime.lastActivity.resultCount}</span>
            ) : <span className={panelStyles.mutedText}>—</span>}
          />
          <VSettingsRow
            label={copy.dailyBudget}
            detail={<span className={panelStyles.detailText}>{runtime.dailyBudget.used} / {runtime.dailyBudget.limit} · {copy.budgetRemaining} {runtime.dailyBudget.remaining}</span>}
          />
        </VSettingsGroupCard>
        <p className={panelStyles.hintText}>{copy.runtimeHint}</p>
      </VSection>
    </div>
  );
}

function RuntimePanel({
  copy, lang, runtime, configuration, pending, error, onRetry, cancelPending, onCancelRun, onOpenSession,
}: {
  copy: Copy;
  lang: "zh" | "en";
  runtime: AgentPerceptionRuntime | null;
  configuration: AgentPerceptionConfiguration | null;
  pending: boolean;
  error?: string | null;
  onRetry: () => void;
  cancelPending: boolean;
  onCancelRun: (runId: string) => void;
  onOpenSession: (sessionId: string) => void;
}) {
  if (pending && !runtime) {
    return <VStateSurface tone="loading" title={copy.runtimeTitle} skeletonLines={2}>{copy.runtimeHint}</VStateSurface>;
  }
  if (error && !runtime) {
    return <VStateSurface tone="error" title={copy.loadFailed} actions={<VButton type="button" onPress={onRetry}>{copy.retry}</VButton>}>{error}</VStateSurface>;
  }
  if (!runtime) {
    return <VStateSurface tone="empty" title={copy.noRun}>{copy.runtimeHint}</VStateSurface>;
  }
  const sources = runtime.readableSources;
  const sourceNames: Record<AgentPerceptionSourceId, string> = {
    personal: copy.personal,
    team: copy.team,
    knowledge: copy.knowledge,
    projects: copy.projects,
  };
  const triggerNames: Record<AgentPerceptionTriggerId, string> = {
    task: copy.triggerTask,
    update: copy.triggerUpdate,
    background: copy.triggerBackground,
  };
  const modeNames = {
    off: copy.modeOff,
    manual: copy.modeManual,
    auto: copy.modeAuto,
  };
  const knowledgeBaseNames = new Map(
    (configuration?.availableScopes.knowledgeBases ?? []).map((base) => [base.id, base.label]),
  );
  return (
    <div className={panelStyles.stack} data-testid="perception-runtime">
      {error ? <VStateSurface tone="error" density="compact" title={copy.loadFailed} actions={<VButton type="button" onPress={onRetry}>{copy.retry}</VButton>}>{error}</VStateSurface> : null}
      <VSettingsGroupCard>
        <VSettingsRow label={copy.runtimeStatus} control={<VChip>{statusLabel(runtime.status, lang)}</VChip>} detail={runtime.nextRunAt ? <span className={panelStyles.mutedText}>{copy.nextRun}: {readableTime(runtime.nextRunAt, lang)}</span> : undefined} />
        <VSettingsRow label={copy.dailyBudget} detail={<span className={panelStyles.detailText}>{runtime.dailyBudget.used} / {runtime.dailyBudget.limit} · {copy.budgetRemaining} {runtime.dailyBudget.remaining}</span>} />
        <VSettingsRow
          label={copy.readableSources}
          footer={sources.length ? (
            <ul className={panelStyles.sourceList}>
              {sources.map((source) => (
                <li key={source.source} className={panelStyles.sourceItem}>
                  <span className={panelStyles.compactStack}>
                    <span className={panelStyles.primaryText}>{sourceNames[source.source]}</span>
                    <span className={panelStyles.tertiaryText}>
                      {copy.mode}: {modeNames[source.mode]} · {copy.activeTriggers}: {TRIGGER_IDS.filter((trigger) => source.triggers[trigger]).map((trigger) => triggerNames[trigger]).join("、") || "—"}
                      {source.requiresUserRequest ? ` · ${copy.requiresUserRequest}` : ""}
                    </span>
                  </span>
                  <span className={panelStyles.tertiaryText}>{copy.selectedCount} {source.selectedCount} · {copy.readableCount} {source.readableCount}</span>
                </li>
              ))}
            </ul>
          ) : <p className={panelStyles.hintText}>{copy.noReadableSources}</p>}
        />
        {runtime.activeRun ? (
          <div className={panelStyles.section}>
            <div className={panelStyles.sectionHeading}>
              <strong className={panelStyles.cardTitle}>{copy.activeRun}</strong>
              {runtime.cancelAvailable ? (
                <VButton type="button" variant="danger" isPending={cancelPending} onPress={() => onCancelRun(runtime.activeRun!.runId)}>
                  {copy.cancel}
                </VButton>
              ) : null}
            </div>
            <RunUsage run={runtime.activeRun} copy={copy} lang={lang} label={statusLabel(runtime.activeRun.status, lang)} sourceNames={sourceNames} onOpenSession={onOpenSession} />
          </div>
        ) : runtime.lastRun ? (
          <div className={panelStyles.section}>
            <RunUsage run={runtime.lastRun} copy={copy} lang={lang} label={copy.lastRun} sourceNames={sourceNames} onOpenSession={onOpenSession} />
          </div>
        ) : null}
      </VSettingsGroupCard>
      <VSettingsGroupCard data-testid="perception-last-activity">
        <VSettingsRow
          label={copy.lastActivity}
          detail={runtime.lastActivity ? (
            <span className={panelStyles.detailText}>
              {copy.trigger}: {triggerNames[runtime.lastActivity.trigger]} · {readableTime(runtime.lastActivity.completedAt, lang)}
            </span>
          ) : <span className={panelStyles.mutedText}>{copy.noRun}</span>}
        />
        {runtime.lastActivity ? (
          <>
            <VSettingsRow
              label={copy.actualSources}
              detail={runtime.lastActivity.sources.length ? (
                <span className={panelStyles.detailText}>{runtime.lastActivity.sources.map((source) => sourceNames[source]).join("、")}</span>
              ) : <span className={panelStyles.mutedText}>{copy.noSourcesRead}</span>}
            />
            <VSettingsRow
              label={copy.usage}
              detail={<span className={panelStyles.detailText}>{copy.readCount}: {runtime.lastActivity.readCount} · {copy.resultCount}: {runtime.lastActivity.resultCount}</span>}
            />
            <VSettingsRow
              label={copy.relatedResult}
              detail={(
                <span className={panelStyles.inlineDetails}>
                  {runtime.lastActivity.sessionId ? (
                    <VButton
                      type="button"
                      variant="ghost"
                      density="compact"
                      aria-label={`${copy.openResearchSession}: ${runtime.lastActivity.sessionId}`}
                      onPress={() => onOpenSession(runtime.lastActivity!.sessionId)}
                    >
                      {copy.openResearchSession}
                    </VButton>
                  ) : null}
                  {runtime.lastActivity.turnId ? <code className={panelStyles.linkedIdentifier}>{runtime.lastActivity.turnId}</code> : null}
                  {runtime.lastActivity.runId ? <code className={panelStyles.linkedIdentifier}>{runtime.lastActivity.runId}</code> : null}
                  {!runtime.lastActivity.sessionId && !runtime.lastActivity.turnId && !runtime.lastActivity.runId ? "—" : null}
                </span>
              )}
            />
          </>
        ) : null}
      </VSettingsGroupCard>
      <VSettingsGroupCard>
        <VSettingsRow
          label={copy.notifications}
          detail={(
            <span className={panelStyles.detailText}>
              {copy.unread} {runtime.notifications.unreadCount} / {runtime.notifications.totalCount}
              {runtime.notifications.suppressedCount !== undefined ? " · " + copy.suppressed + " " + runtime.notifications.suppressedCount : ""}
            </span>
          )}
        />
        {runtime.notifications.items.length ? (
          <ul className={panelStyles.updateList}>
            {runtime.notifications.items.map((item) => (
              <NotificationRow
                key={item.notificationId}
                item={item}
                copy={copy}
                lang={lang}
                knowledgeBaseName={item.knowledgeBaseId === "local-project-governance"
                  ? copy.projects
                  : knowledgeBaseNames.get(item.knowledgeBaseId) ?? ""}
                onOpenSession={onOpenSession}
              />
            ))}
          </ul>
        ) : <VSettingsRow label={copy.notifications} detail={<span className={panelStyles.mutedText}>{copy.noNotifications}</span>} />}
      </VSettingsGroupCard>
      <p className={panelStyles.hintText}>{copy.runtimeHint}</p>
    </div>
  );
}

export function AgentPerceptionPanel({
  agentId, lang, configuration, configurationPending, configurationError, onRetryConfiguration,
  runtime, runtimePending, runtimeError, onRetryRuntime, savePending, saveError, onSave,
  onOpenSession, draftStore, cancelPending, cancelError, onCancelRun,
}: AgentPerceptionPanelProps) {
  const [activeTab, setActiveTab] = useState<"settings" | "history">("settings");
  const copy = useMemo(() => copyFor(lang), [lang]);
  const currentConfiguration = configuration?.agentId === agentId ? configuration : null;
  const draft = useAgentPerceptionDraft(agentId, currentConfiguration, draftStore);
  const validationError = validateAgentPerceptionPolicy(draft.policy);
  const canSave = Boolean(currentConfiguration && currentConfiguration.agentUpdatedAt && draft.isReady && draft.isDirty && !draft.hasConflict && !configurationError && !savePending && !validationError);
  const updatePolicy = draft.update;
  const updateNumber = (
    field: "intervalMinutes" | "dailyMaxRuns" | "maxCallsPerRun" | "maxInputTokensPerRun" | "maxResultChars",
    value: number,
  ) => updatePolicy((current) => ({ ...current, background: { ...current.background, [field]: value } }));

  useEffect(() => {
    setActiveTab("settings");
  }, [agentId]);

  return (
    <div className={panelStyles.panel} data-vui-region="agent-perception-panel" data-testid="agent-perception-panel">
      <VSection title={copy.title} meta={currentConfiguration?.configured ? copy.configured : copy.notConfigured}>
        <p className={panelStyles.description}>{copy.description}</p>
        {currentConfiguration?.configured === false ? <VStateSurface tone="info" density="compact" title={copy.notConfigured}>{copy.legacyHint}</VStateSurface> : null}
        {configurationError ? (
          <VStateSurface
            tone="error"
            density="compact"
            title={copy.loadFailed}
            actions={<VButton type="button" onPress={onRetryConfiguration}>{copy.retry}</VButton>}
          >
            {configurationError}
          </VStateSurface>
        ) : null}
        {currentConfiguration && draft.hasConflict ? (
          <VStateSurface
            data-testid="agent-perception-policy-conflict"
            tone="info"
            density="compact"
            title={copy.revisionConflictTitle}
            actions={<VButton type="button" onPress={draft.reset}>{copy.reloadLatest}</VButton>}
          >
            {copy.revisionConflictMessage}
          </VStateSurface>
        ) : null}
      </VSection>
      {saveError ? <VStateSurface tone="error" density="compact" title={copy.loadFailed}>{saveError}</VStateSurface> : null}
      <div data-testid="agent-perception-tabs">
        <VTabs
          aria-label={copy.title}
          value={activeTab}
          onValueChange={(value) => {
            if (value === "settings" || value === "history") setActiveTab(value);
          }}
          items={[
            { id: "settings", label: copy.settingsTab },
            { id: "history", label: copy.historyTab },
          ]}
        />
      </div>
      <VSplitWorkspace
        className={panelStyles.workspace}
        data-testid="agent-perception-workspace"
        resize={{
          layoutId: WORKBENCH_LAYOUT_IDS.agentPerception,
          aside: { id: "runtime", defaultWidth: 340, minWidth: 260, maxWidth: 480 },
        }}
        main={(
          <div className={panelStyles.mainContent} data-testid={`agent-perception-tab-${activeTab}`}>
            {activeTab === "settings" ? (
              <VSection title={copy.settingsTab} meta={currentConfiguration?.configured ? copy.configured : copy.notConfigured}>
                {configurationError && !currentConfiguration ? (
                  <VStateSurface tone="error" title={copy.loadFailed} actions={<VButton type="button" onPress={onRetryConfiguration}>{copy.retry}</VButton>}>{configurationError}</VStateSurface>
                ) : !currentConfiguration || configurationPending ? (
                  <VStateSurface tone="loading" title={copy.title} skeletonLines={2} />
                ) : (
                  <>
                    <VSettingsGroupCard>
                      <VSettingsRow
                        label={copy.enabled}
                        description={copy.enabledHint}
                        control={<VSwitch aria-label={copy.enabled} isSelected={draft.policy.enabled} onChange={(enabled) => updatePolicy((current) => ({ ...current, enabled }))} />}
                        status={<VChip>{draft.policy.enabled ? copy.modeAuto : copy.modeOff}</VChip>}
                        footer={<p className={panelStyles.hintText}>{copy.notGranted}</p>}
                      />
                    </VSettingsGroupCard>
                    <div className={panelStyles.sectionStack}>
                      <VSection title={copy.sourceTitle}><p className={panelStyles.ruleText}>{copy.sourceHint}</p></VSection>
                      <div className={panelStyles.sourceGrid}>
                        {SOURCE_IDS.map((source) => (
                          <SourceCard
                            key={source}
                            copy={copy}
                            lang={lang}
                            source={source}
                            policy={draft.policy}
                            options={source === "team" ? currentConfiguration.availableScopes.teams : source === "knowledge" ? currentConfiguration.availableScopes.knowledgeBases : undefined}
                            updatePolicy={updatePolicy}
                          />
                        ))}
                      </div>
                    </div>
                    <div className={panelStyles.sectionStack}>
                      <VSection title={copy.backgroundTitle}><p className={panelStyles.ruleText}>{copy.backgroundHint}</p></VSection>
                      <VSettingsGroupCard>
                        <VSettingsRow
                          label={copy.backgroundEnabled}
                          description={langText(lang, "只有启用后台计划后，后台触发器才会运行。", "Background triggers run only while a schedule is enabled.")}
                          control={<VSwitch aria-label={copy.backgroundEnabled} isSelected={draft.policy.background.enabled} onChange={(enabled) => updatePolicy((current) => ({ ...current, background: { ...current.background, enabled } }))} />}
                        />
                        <NumberSetting id="perception-background-interval" label={copy.interval} description={copy.intervalHint} value={draft.policy.background.intervalMinutes} min={15} max={10_080} onChange={(value) => updateNumber("intervalMinutes", value)} />
                        <NumberSetting id="perception-background-daily-runs" label={copy.dailyMaxRuns} value={draft.policy.background.dailyMaxRuns} min={0} max={96} onChange={(value) => updateNumber("dailyMaxRuns", value)} />
                        <NumberSetting id="perception-background-calls" label={copy.maxCalls} value={draft.policy.background.maxCallsPerRun} min={1} max={32} onChange={(value) => updateNumber("maxCallsPerRun", value)} />
                        <NumberSetting id="perception-background-input-tokens" label={copy.maxInputTokens} value={draft.policy.background.maxInputTokensPerRun} min={1} max={131_072} onChange={(value) => updateNumber("maxInputTokensPerRun", value)} />
                        <NumberSetting id="perception-background-result-chars" label={copy.maxResultChars} value={draft.policy.background.maxResultChars} min={1} max={50_000} onChange={(value) => updateNumber("maxResultChars", value)} />
                        <VSettingsRow label={copy.concurrent} detail={<span className={panelStyles.detailText}>{draft.policy.background.maxConcurrent}</span>} />
                        <TopicEditor topics={draft.policy.background.topics} copy={copy} onChange={(topics) => updatePolicy((current) => ({ ...current, background: { ...current.background, topics } }))} />
                      </VSettingsGroupCard>
                      <VSettingsGroupCard>
                        <VSettingsRow
                          label={copy.notificationMode}
                          description={copy.notificationHint}
                          control={(
                            <VNativeSelect
                              aria-label={copy.notificationMode}
                              value={draft.policy.notifications.mode}
                              onChange={(event) => updatePolicy((current) => ({ ...current, notifications: { mode: event.currentTarget.value as AgentPerceptionPolicy["notifications"]["mode"] } }))}
                            >
                              <option value="important">{copy.notificationsImportant}</option>
                              <option value="all">{copy.notificationsAll}</option>
                              <option value="quiet">{copy.notificationsQuiet}</option>
                            </VNativeSelect>
                          )}
                        />
                      </VSettingsGroupCard>
                    </div>
                    <div className={panelStyles.rowHeading}>
                      <div className={panelStyles.compactStack}>
                        <span className={panelStyles.saveState}>{draft.isDirty ? copy.dirty : copy.saved}</span>
                        <span className={panelStyles.mutedText}>{copy.savedHint}</span>
                      </div>
                      <div className={panelStyles.actions}>
                        <VButton type="button" isDisabled={!draft.isDirty || savePending} onPress={draft.reset}>{copy.discard}</VButton>
                        <VButton
                          type="button"
                          data-testid="agent-perception-save"
                          variant="primary"
                          isPending={savePending}
                          isDisabled={!canSave}
                          onPress={() => {
                            if (currentConfiguration.agentUpdatedAt && !validationError) onSave(draft.policy, currentConfiguration.agentUpdatedAt);
                          }}
                        >
                          {copy.save}
                        </VButton>
                      </div>
                    </div>
                    {validationError ? <VStateSurface tone="error" density="compact" title={copy.invalidPolicy}>{validationError}</VStateSurface> : null}
                  </>
                )}
              </VSection>
            ) : (
              <VSection title={copy.historyTab} meta={runtime?.updatedAt ? readableTime(runtime.updatedAt, lang) : undefined}>
                <p className={panelStyles.paragraph}>{copy.historyHint}</p>
                <RuntimePanel copy={copy} lang={lang} runtime={runtime} configuration={currentConfiguration} pending={runtimePending} error={runtimeError} onRetry={onRetryRuntime} cancelPending={cancelPending} onCancelRun={onCancelRun} onOpenSession={onOpenSession} />
                {cancelError ? <VStateSurface tone="error" density="compact" title={copy.loadFailed}>{cancelError}</VStateSurface> : null}
              </VSection>
            )}
          </div>
        )}
        aside={(
          <div className={panelStyles.runtimeAside}>
            <RuntimeSummary copy={copy} lang={lang} runtime={runtime} pending={runtimePending} error={runtimeError} onRetry={onRetryRuntime} />
          </div>
        )}
      />
    </div>
  );
}
