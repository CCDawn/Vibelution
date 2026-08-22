/**
 * Isolated interactive VUI preview for a calmer Agent configuration information
 * architecture. Review-only — does NOT modify the formal /agents route and does
 * NOT call any backend API. All save / run / delete actions are safe mock copy.
 *
 * Open: /agent-management-focus-preview.html
 */
import { StrictMode, useEffect, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  LayoutDashboard,
  Search,
  Settings2,
  X,
} from "lucide-react";

import {
  VActionGroup,
  VButton,
  VCheckbox,
  VConfirmDialog,
  VEntityList,
  VFieldRow,
  VIconButton,
  VInput,
  VListDetailPage,
  VMetricStrip,
  VNativeButton,
  VNativeSelect,
  VStatusChip,
  VSurface,
  VTabs,
  VNativeTextarea,
  VuiProvider,
} from "../components/vui";
import "./tokens.css";
import "./base.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";
import "./agent-management-focus-preview.css";
import { agentManagementFocusPreviewStyles as styles } from "./agent-management-focus-preview.styles";

type PrimaryTab = "overview" | "config" | "activity";

type Agent = {
  id: string;
  name: string;
  role: string;
  model: string;
  online: boolean;
  initial: string;
};

type ConfigDraft = {
  name: string;
  role: string;
  systemPrompt: string;
  model: string;
  temperature: string;
  tools: string[];
  memory: string;
  budget: string;
  advancedLogging: boolean;
};

type InspectorState = { kind: "test" } | { kind: "review" } | null;

const AGENTS: Agent[] = [
  { id: "agent-ingestor", name: "资料入库", role: "source_ingestor", model: "qwen-plus", online: true, initial: "资" },
  { id: "agent-finder", name: "白望舒", role: "source_finder", model: "deepseek-v3", online: true, initial: "白" },
  { id: "agent-extractor", name: "顾言初", role: "extractor", model: "claude-sonnet-4", online: false, initial: "顾" },
  { id: "agent-synthesizer", name: "沈观止", role: "synthesizer", model: "qwen-plus", online: true, initial: "沈" },
  { id: "agent-reviewer", name: "周衡", role: "reviewer", model: "deepseek-v3", online: true, initial: "周" },
];

const BASE_DRAFT: ConfigDraft = {
  name: "资料入库",
  role: "source_ingestor",
  systemPrompt: "负责把检索到的资料清洗、去重并写入证据库，输出结构化条目。",
  model: "qwen-plus",
  temperature: "0.3",
  tools: ["search", "write_memory", "extract"],
  memory: "对话与工具记忆",
  budget: "标准",
  advancedLogging: true,
};

const MODEL_OPTIONS = ["qwen-plus", "deepseek-v3", "claude-sonnet-4"];
const TOOL_OPTIONS = ["search", "write_memory", "extract", "browse", "code_run"];
const MEMORY_OPTIONS = ["仅对话", "对话与工具记忆", "长程上下文"];
const BUDGET_OPTIONS = ["标准", "紧凑", "宽松"];

const PRIMARY_TABS: { id: PrimaryTab; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "概览", icon: LayoutDashboard },
  { id: "config", label: "配置", icon: Settings2 },
  { id: "activity", label: "活动", icon: Activity },
];

function initialDraftFor(agent: Agent): ConfigDraft {
  return { ...BASE_DRAFT, name: agent.name, role: agent.role, model: agent.model };
}

function countDraftChanges(draft: ConfigDraft, baseline: ConfigDraft): number {
  let count = 0;
  if (draft.name !== baseline.name) count += 1;
  if (draft.role !== baseline.role) count += 1;
  if (draft.systemPrompt !== baseline.systemPrompt) count += 1;
  if (draft.model !== baseline.model) count += 1;
  if (draft.temperature !== baseline.temperature) count += 1;
  if (draft.tools.join(",") !== baseline.tools.join(",")) count += 1;
  if (draft.memory !== baseline.memory) count += 1;
  if (draft.budget !== baseline.budget) count += 1;
  if (draft.advancedLogging !== baseline.advancedLogging) count += 1;
  return count;
}

function SectionChevron({ open }: { open: boolean }) {
  return open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />;
}

function DirectoryItem(props: {
  agent: Agent;
  active: boolean;
  bulkMode: boolean;
  selected: boolean;
  onSelect: (agent: Agent) => void;
  onToggle: (agentId: string, selected: boolean) => void;
}) {
  const { agent, active, bulkMode, selected, onSelect, onToggle } = props;
  return (
    <div
      data-active={active ? "true" : undefined}
      data-bulk-mode={bulkMode ? "true" : undefined}
      className={`${styles.directoryItem} ${active ? styles.directoryItemActive : ""}`}
    >
      {bulkMode ? (
        <VCheckbox
          aria-label={`选择 ${agent.name}`}
          isSelected={selected}
          onChange={(next) => onToggle(agent.id, next)}
          className={styles.directoryItemCheck}
        />
      ) : null}
      <VNativeButton
        type="button"
        className={styles.directoryItemBody}
        aria-current={active ? "page" : undefined}
        onClick={() => onSelect(agent)}
      >
        <span className={styles.directoryItemName}>{agent.name}</span>
        <span className={styles.directoryItemMeta}>{agent.role}</span>
      </VNativeButton>
    </div>
  );
}

const OVERVIEW_ATTENTION = [
  { title: "工具待审批", detail: "browse 权限申请 1 条待批" },
  { title: "提示词 v4 待审查", detail: "距上次审查已 3 天" },
  { title: "模型延迟升高", detail: "近 3 轮平均延迟 +28%" },
];

const OVERVIEW_RUN_HEALTH = [
  { label: "近 24h 运行", value: "23 次" },
  { label: "成功率", value: "96%" },
  { label: "P95 延迟", value: "8.4s" },
  { label: "待审批", value: "1 条" },
];

const OVERVIEW_ACTIVITY = [
  { time: "10:41", text: "证据提取批次 #6", status: "成功", tone: "success", meta: "38s · v4" },
  { time: "10:28", text: "更新系统提示词", status: "成功", tone: "success", meta: "revision 12" },
  { time: "09:52", text: "校验模型配置", status: "成功", tone: "success", meta: "config snapshot" },
  { time: "09:41", text: "资料检索批次 #5", status: "重试", tone: "warning", meta: "3 次 · 91s" },
  { time: "09:12", text: "知识库入库", status: "成功", tone: "success", meta: "12 条" },
  { time: "08:47", text: "记忆清理", status: "成功", tone: "success", meta: "2 项" },
];

function OverviewView({ agent }: { agent: Agent }) {
  return (
    <div className={styles.overviewLayout}>
      <div className={styles.overviewMain}>
        <VSurface as="section" className={styles.overviewCard} ariaLabel="有效配置">
          <h3 className={styles.overviewCardTitle}>有效配置</h3>
          <dl className={styles.overviewRows}>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>模型 / 温度</dt>
              <dd className={styles.overviewRowValue}>{agent.model} · 0.3</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>指令版本</dt>
              <dd className={styles.overviewRowValue}>v4 · revision 12</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>工具 / Action groups</dt>
              <dd className={styles.overviewRowValue}>search · write_memory · extract</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>知识库</dt>
              <dd className={styles.overviewRowValue}>research-evidence · 12 条</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>权限 / Guardrail</dt>
              <dd className={styles.overviewRowValue}>标准只读 · 禁删除</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>记忆</dt>
              <dd className={styles.overviewRowValue}>对话与工具记忆</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>会话超时</dt>
              <dd className={styles.overviewRowValue}>30 分钟</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>运行边界</dt>
              <dd className={styles.overviewRowValue}>标准预算 · 单轮 30 分钟</dd>
            </div>
          </dl>
        </VSurface>

        <VSurface as="section" className={styles.overviewCard} ariaLabel="最近活动">
          <h3 className={styles.overviewCardTitle}>最近活动</h3>
          <div className={styles.overviewActivity}>
            {OVERVIEW_ACTIVITY.map((item) => (
              <div key={`${item.time}-${item.text}`} className={styles.activityRow}>
                <time className={styles.activityTime}>{item.time}</time>
                <div className={styles.activityRowBody}>
                  <span className={styles.activityRowText}>{item.text}</span>
                  <span className={styles.activityRowMeta}>{item.meta}</span>
                </div>
                <VStatusChip tone={item.tone as "success" | "warning"}>{item.status}</VStatusChip>
              </div>
            ))}
          </div>
        </VSurface>
      </div>

      <div className={styles.overviewSide}>
        <VSurface as="section" className={styles.overviewCard} ariaLabel="身份与团队">
          <h3 className={styles.overviewCardTitle}>身份与团队</h3>
          <dl className={styles.overviewRows}>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>角色</dt>
              <dd className={styles.overviewRowValue}>{agent.role}</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>团队</dt>
              <dd className={styles.overviewRowValue}>挑战杯科研</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>主管</dt>
              <dd className={styles.overviewRowValue}>team-lead-agent</dd>
            </div>
            <div className={styles.overviewRow}>
              <dt className={styles.overviewRowLabel}>协作 Agent</dt>
              <dd className={styles.overviewRowValue}>3</dd>
            </div>
          </dl>
        </VSurface>

        <VSurface as="section" className={styles.overviewCard} ariaLabel="运行健康">
          <h3 className={styles.overviewCardTitle}>运行健康</h3>
          <dl className={styles.overviewRows}>
            {OVERVIEW_RUN_HEALTH.map((item) => (
              <div key={item.label} className={styles.overviewRow}>
                <dt className={styles.overviewRowLabel}>{item.label}</dt>
                <dd className={styles.overviewRowValue}>{item.value}</dd>
              </div>
            ))}
          </dl>
        </VSurface>

        <VSurface as="section" className={styles.overviewCard} ariaLabel="需要关注">
          <h3 className={styles.overviewCardTitle}>需要关注</h3>
          <div className={styles.attentionList}>
            {OVERVIEW_ATTENTION.map((item) => (
              <div key={item.title} className={styles.attentionItem}>
                <VStatusChip tone="warning">{item.title}</VStatusChip>
                <span className={styles.attentionDetail}>{item.detail}</span>
              </div>
            ))}
          </div>
        </VSurface>
      </div>
    </div>
  );
}

function ConfigSection(props: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const { title, open, onToggle, children } = props;
  return (
    <VSurface as="section" className={styles.configSection} ariaLabel={title}>
      <VNativeButton
        type="button"
        className={styles.configSectionHeader}
        aria-expanded={open}
        onClick={onToggle}
      >
        <SectionChevron open={open} />
        <span className={styles.configSectionTitle}>{title}</span>
      </VNativeButton>
      {open ? <div className={styles.configSectionBody}>{children}</div> : null}
    </VSurface>
  );
}

function ConfigView(props: {
  draft: ConfigDraft;
  onChange: (patch: Partial<ConfigDraft>) => void;
}) {
  const { draft, onChange } = props;
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    basics: true,
    role: false,
    capability: false,
    advanced: false,
  });
  const toggle = (key: string) =>
    setOpenSections((current) => ({ ...current, [key]: !current[key] }));

  const toolToggle = (tool: string, selected: boolean) => {
    const next = selected
      ? [...draft.tools, tool]
      : draft.tools.filter((item) => item !== tool);
    onChange({ tools: next });
  };

  return (
    <div className={styles.configSections}>
      <ConfigSection title="基础信息" open={openSections.basics} onToggle={() => toggle("basics")}>
        <div className={styles.configFields}>
          <VFieldRow label="名称" className={styles.configField}>
            <VInput
              aria-label="名称"
              value={draft.name}
              onChange={(event) => onChange({ name: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label="角色" className={styles.configField}>
            <VInput
              aria-label="角色"
              value={draft.role}
              onChange={(event) => onChange({ role: event.target.value })}
            />
          </VFieldRow>
        </div>
      </ConfigSection>

      <ConfigSection title="角色与提示词" open={openSections.role} onToggle={() => toggle("role")}>
        <div className={styles.configFields}>
          <VFieldRow label="系统提示词" className={styles.configField}>
            <VNativeTextarea
              aria-label="系统提示词"
              value={draft.systemPrompt}
              onChange={(event) => onChange({ systemPrompt: event.target.value })}
              minRows={3}
            />
          </VFieldRow>
        </div>
      </ConfigSection>

      <ConfigSection title="能力与权限" open={openSections.capability} onToggle={() => toggle("capability")}>
        <div className={styles.configFields}>
          <VFieldRow label="模型" className={styles.configField}>
            <VNativeSelect
              aria-label="模型"
              value={draft.model}
              onChange={(event) => onChange({ model: event.target.value })}
            >
              {MODEL_OPTIONS.map((model) => (
                <option key={model} value={model}>{model}</option>
              ))}
            </VNativeSelect>
          </VFieldRow>
          <VFieldRow label="温度" className={styles.configField}>
            <VInput
              aria-label="温度"
              value={draft.temperature}
              onChange={(event) => onChange({ temperature: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label="工具" className={styles.configField}>
            <div className={styles.capabilityList}>
              {TOOL_OPTIONS.map((tool) => (
                <VCheckbox
                  key={tool}
                  aria-label={`工具 ${tool}`}
                  isSelected={draft.tools.includes(tool)}
                  onChange={(next) => toolToggle(tool, next)}
                >
                  {tool}
                </VCheckbox>
              ))}
            </div>
          </VFieldRow>
        </div>
      </ConfigSection>

      <ConfigSection title="高级设置" open={openSections.advanced} onToggle={() => toggle("advanced")}>
        <div className={styles.configFields}>
          <VFieldRow label="记忆" className={styles.configField}>
            <VNativeSelect
              aria-label="记忆"
              value={draft.memory}
              onChange={(event) => onChange({ memory: event.target.value })}
            >
              {MEMORY_OPTIONS.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </VNativeSelect>
          </VFieldRow>
          <VFieldRow label="预算档位" className={styles.configField}>
            <VNativeSelect
              aria-label="预算档位"
              value={draft.budget}
              onChange={(event) => onChange({ budget: event.target.value })}
            >
              {BUDGET_OPTIONS.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </VNativeSelect>
          </VFieldRow>
          <VFieldRow label="详细日志" className={styles.configField}>
            <VCheckbox
              aria-label="详细日志"
              isSelected={draft.advancedLogging}
              onChange={(next) => onChange({ advancedLogging: next })}
            >
              开启
            </VCheckbox>
          </VFieldRow>
        </div>
      </ConfigSection>
    </div>
  );
}

const ACTIVITY_ITEMS = [
  { time: "10:34", text: "完成一轮证据提取 · 12 条" },
  { time: "10:28", text: "更新系统提示词" },
  { time: "09:52", text: "切换模型为 qwen-plus" },
];

function ActivityView() {
  return (
    <div className={styles.activityList}>
      {ACTIVITY_ITEMS.map((item) => (
        <VSurface as="article" key={item.time} className={styles.activityItem} ariaLabel={`活动 ${item.time}`}>
          <time className={styles.activityTime}>{item.time}</time>
          <span>{item.text}</span>
        </VSurface>
      ))}
    </div>
  );
}

function InspectorDrawer(props: {
  inspector: InspectorState;
  unsavedCount: number;
  onClose: () => void;
}) {
  const { inspector, unsavedCount, onClose } = props;
  const [testResult, setTestResult] = useState<string | null>(null);
  useEffect(() => {
    setTestResult(null);
  }, [inspector?.kind]);
  if (!inspector) return null;
  const isTest = inspector.kind === "test";

  return (
    <VSurface as="aside" className={styles.inspectorSurface} ariaLabel={isTest ? "测试面板" : "变更审查"}>
      <header className={styles.inspectorHeader}>
        <h3 className={styles.inspectorTitle}>{isTest ? "测试" : "审查并保存"}</h3>
        <VIconButton label="关闭" icon={<X size={15} />} variant="ghost" onClick={onClose} />
      </header>
      <div className={styles.inspectorBody}>
        {isTest ? (
          <>
            <p className={styles.mockNote}>安全的 Mock 测试控件 · 不会调用任何运行接口。</p>
            <div className={styles.inspectorField}>
              <VFieldRow label="测试输入">
                <VInput aria-label="测试输入" placeholder="输入一段提示词…" />
              </VFieldRow>
            </div>
            <VActionGroup ariaLabel="测试动作">
              <VButton
                type="button"
                variant="primary"
                onClick={() => setTestResult("Mock 运行完成 · 无 API 连接")}
              >
                运行 Mock
              </VButton>
            </VActionGroup>
            {testResult ? (
              <div className={styles.inspectorResult} role="status">
                {testResult}
              </div>
            ) : null}
          </>
        ) : (
          <>
            <p className={styles.mockNote}>预览中的保存是 Mock · 不会写任何数据。</p>
            <div className={styles.inspectorField}>
              <VFieldRow label="待确认变更">
                <span className={styles.unsavedCount}>{unsavedCount} 处</span>
              </VFieldRow>
            </div>
            <VActionGroup ariaLabel="保存动作">
              <VButton
                type="button"
                variant="primary"
                onClick={() => setTestResult("Mock 已接收审查 · 无保存 API 连接")}
              >
                确认保存（Mock）
              </VButton>
            </VActionGroup>
            {testResult ? (
              <div className={styles.inspectorResult} role="status">
                {testResult}
              </div>
            ) : null}
          </>
        )}
      </div>
    </VSurface>
  );
}

export function AgentManagementFocusPreviewApp() {
  const [primaryTab, setPrimaryTab] = useState<PrimaryTab>("overview");
  const [selectedAgentId, setSelectedAgentId] = useState(AGENTS[0].id);
  const [query, setQuery] = useState("");
  const [bulkMode, setBulkMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState<ConfigDraft>(() => initialDraftFor(AGENTS[0]));
  const [inspector, setInspector] = useState<InspectorState>(null);
  const [pendingAgentId, setPendingAgentId] = useState<string | null>(null);

  const selectedAgent = useMemo(
    () => AGENTS.find((agent) => agent.id === selectedAgentId) ?? AGENTS[0],
    [selectedAgentId],
  );

  const filteredAgents = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return AGENTS;
    return AGENTS.filter((agent) =>
      `${agent.name} ${agent.role} ${agent.model}`.toLowerCase().includes(needle),
    );
  }, [query]);

  const unsavedCount = useMemo(
    () => countDraftChanges(draft, initialDraftFor(selectedAgent)),
    [draft, selectedAgent],
  );

  const commitAgentSelection = (agent: Agent) => {
    setSelectedAgentId(agent.id);
    setDraft(initialDraftFor(agent));
    setInspector(null);
    setPendingAgentId(null);
  };

  const selectAgent = (agent: Agent) => {
    if (agent.id === selectedAgent.id) return;
    if (unsavedCount > 0) {
      setPendingAgentId(agent.id);
      return;
    }
    commitAgentSelection(agent);
  };

  const toggleBulk = (agentId: string, selected: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (selected) next.add(agentId);
      else next.delete(agentId);
      return next;
    });
  };

  const openTest = () => setInspector({ kind: "test" });

  const headerActions = (
    <VActionGroup ariaLabel="Agent 详情动作">
      <VButton type="button" variant="secondary" onClick={() => setBulkMode((value) => !value)}>
        {bulkMode ? "退出批量管理" : "批量管理"}
      </VButton>
      <VButton type="button" variant="secondary" icon={<FlaskConical size={14} />} onClick={openTest}>
        测试
      </VButton>
    </VActionGroup>
  );

  const list = (
    <VSurface as="section" className={styles.directorySurface} ariaLabel="Agent 目录" tone="rail" padding="compact">
      <header className={styles.directoryHeader}>
        <span>Agent</span>
        <span>{AGENTS.length}</span>
      </header>
      <label className={styles.directorySearch}>
        <Search size={14} aria-hidden="true" />
        <VInput
          aria-label="搜索 Agent"
          placeholder="搜索 Agent"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {bulkMode ? (
        <div className={styles.bulkBar} role="status">
          批量管理：已选 {selectedIds.size} / {filteredAgents.length}
        </div>
      ) : null}
      <VEntityList
        ariaLabel="Agent 目录"
        activeId={selectedAgentId}
        items={filteredAgents}
        renderItem={(agent) => (
          <DirectoryItem
            agent={agent}
            active={agent.id === selectedAgentId}
            bulkMode={bulkMode}
            selected={selectedIds.has(agent.id)}
            onSelect={selectAgent}
            onToggle={toggleBulk}
          />
        )}
        empty={<div className={styles.directoryEmpty}>无匹配 Agent</div>}
      />
    </VSurface>
  );

  const detail = (
    <div className={styles.detailScroll}>
      <div className={styles.detailPane}>
        <VMetricStrip
          ariaLabel="Agent 摘要"
          metrics={[
            { label: "状态", value: selectedAgent.online ? "在线" : "离线", tone: selectedAgent.online ? "success" : "warning" },
            { label: "模型", value: selectedAgent.model },
            { label: "版本", value: "revision 12" },
            { label: "最近运行", value: "2 分钟前" },
          ]}
        />
        <VTabs
          className={styles.primaryTabs}
          data-vui="primary-tabs"
          aria-label="Agent 详情视图"
          value={primaryTab}
          onValueChange={(value) => {
            setPrimaryTab(value as PrimaryTab);
            setInspector(null);
          }}
          items={PRIMARY_TABS.map((tab) => ({
            id: tab.id,
            label: tab.label,
          }))}
        />

        {primaryTab === "overview" ? <OverviewView agent={selectedAgent} /> : null}
        {primaryTab === "config" ? (
          <ConfigView draft={draft} onChange={(patch) => setDraft((current) => ({ ...current, ...patch }))} />
        ) : null}
        {primaryTab === "activity" ? <ActivityView /> : null}

        {unsavedCount > 0 ? (
          <div className={styles.unsavedBar} data-testid="unsaved-bar" role="status">
            <span className={styles.unsavedCount}>未保存变更 {unsavedCount} 处</span>
            <div className={styles.unsavedActions}>
              <VButton type="button" variant="ghost" onClick={() => setDraft(initialDraftFor(selectedAgent))}>
                放弃
              </VButton>
              <VButton
                type="button"
                variant="primary"
                onClick={() => setInspector({ kind: "review" })}
              >
                审查并保存
              </VButton>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );

  const aside = inspector ? (
    <InspectorDrawer
      inspector={inspector}
      unsavedCount={unsavedCount}
      onClose={() => setInspector(null)}
    />
  ) : null;

  const pendingAgent = pendingAgentId
    ? AGENTS.find((agent) => agent.id === pendingAgentId) ?? null
    : null;

  const workspaceLayout = `${styles.workspaceClass} ${
    inspector ? styles.workspaceThreeCol : styles.workspaceTwoCol
  }`;

  return (
    <>
      <VListDetailPage
        className={styles.page}
        workspaceClassName={workspaceLayout}
        columnsClassName=""
        ariaLabel="Agent 配置信息架构预览"
        title={selectedAgent.name}
        meta={`${selectedAgent.role} · 挑战杯科研`}
        actions={headerActions}
        list={list}
        detail={detail}
        aside={aside}
      />
      <VConfirmDialog
        open={pendingAgent !== null}
        title="放弃未保存变更并切换 Agent？"
        description={pendingAgent ? `当前草稿尚未保存。切换到「${pendingAgent.name}」会放弃这些变更。` : undefined}
        confirmLabel="放弃并切换"
        cancelLabel="取消"
        onOpenChange={(open) => {
          if (!open) setPendingAgentId(null);
        }}
        onCancel={() => setPendingAgentId(null)}
        onConfirm={() => {
          if (pendingAgent) commitAgentSelection(pendingAgent);
        }}
      />
    </>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <AgentManagementFocusPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
