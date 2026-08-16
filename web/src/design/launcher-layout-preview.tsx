import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { GitBranch } from "lucide-react";

import {
  VButton,
  VChip,
  VDenseTable,
  type VDenseTableColumn,
  VEmptyState,
  VInput,
  VStatusChip,
  type VStatusTone,
  VStringSelect,
  VSurface,
  VTabs,
  type VTabsItem,
  VuiProvider,
  type VuiTone,
} from "../components/vui";

import "./tokens.css";
import "./vui-provider-theme.css";
import "./vui-component-preview/preview.tailwind.css";
import { launcherLayoutPreviewStyles as styles } from "./launcher-layout-preview.styles";

type InstanceState = "running" | "attention" | "stopped";
type RiskLevel = "low" | "medium" | "high";
type TabId = "all" | "running" | "attention" | "stopped";
type ScenarioId = "running" | "attention" | "empty";

type BranchInstance = {
  id: string;
  branch: string;
  kind: string;
  state: InstanceState;
  stateLabel: string;
  path: string;
  backend: string;
  window: string;
  updated: string;
  risk: RiskLevel;
};

const SCENARIOS: Record<ScenarioId, BranchInstance[]> = {
  running: [
    { id: "run-main", branch: "main", kind: "当前 main", state: "running", stateLabel: "运行中", path: "C:\\dev\\Vibelution", backend: "8000", window: "已打开", updated: "10:27", risk: "low" },
    { id: "run-preview", branch: "feature/launcher-layout", kind: "任务分支", state: "running", stateLabel: "运行中", path: ".worktrees\\launcher-layout-preview", backend: "8001", window: "已打开", updated: "10:18", risk: "low" },
    { id: "run-evo", branch: "feature/evolution", kind: "任务分支", state: "running", stateLabel: "运行中", path: ".worktrees\\evolution", backend: "8002", window: "已打开", updated: "09:42", risk: "medium" },
    { id: "run-legacy", branch: "legacy-checkout", kind: "旧目录", state: "stopped", stateLabel: "已停止", path: "D:\\Vibelution-worktrees", backend: "—", window: "未打开", updated: "昨天", risk: "low" },
  ],
  attention: [
    { id: "att-main", branch: "main", kind: "当前 main", state: "attention", stateLabel: "需处理", path: "C:\\dev\\Vibelution", backend: "8000", window: "异常", updated: "10:05", risk: "high" },
    { id: "att-evo", branch: "feature/evolution", kind: "任务分支", state: "running", stateLabel: "运行中", path: ".worktrees\\evolution", backend: "8002", window: "已打开", updated: "09:58", risk: "medium" },
    { id: "att-retired", branch: "retired/team-cleanup", kind: "退役", state: "attention", stateLabel: "需处理", path: ".worktrees\\retired", backend: "—", window: "残留进程", updated: "08/12", risk: "medium" },
  ],
  empty: [],
};

const SCENARIO_LABEL: Record<ScenarioId, string> = {
  running: "运行中",
  attention: "需处理",
  empty: "全空",
};

const TAB_LABEL: Record<TabId, string> = {
  all: "全部",
  running: "运行中",
  attention: "需处理",
  stopped: "已停止",
};

const RISK_OPTIONS = [
  { value: "all", label: "全部风险" },
  { value: "low", label: "低风险" },
  { value: "medium", label: "中风险" },
  { value: "high", label: "高风险" },
] as const;

const RISK_LABEL: Record<RiskLevel, string> = { low: "低", medium: "中", high: "高" };
const RISK_TONE: Record<RiskLevel, VuiTone> = { low: "success", medium: "warning", high: "danger" };

const PROFILE_OPTIONS = [
  { value: "development", label: "development" },
  { value: "performance", label: "performance" },
] as const;

const WINDOW_MODE_OPTIONS = [
  { value: "windowed", label: "窗口化" },
  { value: "fullscreen", label: "全屏" },
] as const;

const WINDOW_SIZE_OPTIONS = [
  { value: "1440x900", label: "1440×900" },
  { value: "1280x800", label: "1280×800" },
  { value: "1920x1080", label: "1920×1080" },
] as const;

const MAINTENANCE_ROWS: ReadonlyArray<[string, string]> = [
  ["维护档位", "factory_runtime"],
  ["清理目标", "缓存 · 构建产物 · 已合并 worktree"],
  ["开发者沙盒", "关闭"],
  ["高级诊断", "无待处理命令"],
];

function stateTone(state: InstanceState): VStatusTone {
  return state === "running" ? "success" : state === "attention" ? "warning" : "neutral";
}

function optionLabel(options: ReadonlyArray<{ value: string; label: string }>, value: string): string {
  return options.find((option) => option.value === value)?.label ?? value;
}

export function LauncherLayoutPreviewApp() {
  const [scenario, setScenario] = useState<ScenarioId>("running");
  const [tab, setTab] = useState<TabId>("all");
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState("all");
  const [startupOpen, setStartupOpen] = useState(false);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [mockNotice, setMockNotice] = useState("");

  const [profile, setProfile] = useState("development");
  const [backendPort, setBackendPort] = useState("8000");
  const [frontendPort, setFrontendPort] = useState("5173");
  const [windowMode, setWindowMode] = useState("windowed");
  const [windowSize, setWindowSize] = useState("1440x900");

  const instances = SCENARIOS[scenario];
  const tabCounts: Record<TabId, number> = {
    all: instances.length,
    running: instances.filter((item) => item.state === "running").length,
    attention: instances.filter((item) => item.state === "attention").length,
    stopped: instances.filter((item) => item.state === "stopped").length,
  };

  const normalizedQuery = query.trim().toLowerCase();
  const filtered = instances.filter((item) => {
    if (tab !== "all" && item.state !== tab) {
      return false;
    }
    if (risk !== "all" && item.risk !== risk) {
      return false;
    }
    if (normalizedQuery && !`${item.branch} ${item.path}`.toLowerCase().includes(normalizedQuery)) {
      return false;
    }
    return true;
  });

  const isEmpty = scenario === "empty" || filtered.length === 0;

  function switchScenario(next: ScenarioId) {
    setScenario(next);
    setTab("all");
    setQuery("");
    setRisk("all");
    setMockNotice(`场景已切换：${SCENARIO_LABEL[next]}（纯 mock 数据）`);
  }

  const tabItems: VTabsItem[] = (["all", "running", "attention", "stopped"] as TabId[]).map((id) => ({
    id,
    label: (
      <span className="inline-flex min-w-0 items-center">
        {TAB_LABEL[id]}
        <span className={styles.count}>{tabCounts[id]}</span>
      </span>
    ),
  }));

  const columns: VDenseTableColumn<BranchInstance>[] = [
    {
      id: "branch",
      header: "分支",
      fill: true,
      minWidth: 140,
      render: (row) => (
        <div className={styles.branchCell}>
          <strong className={styles.branchName}>{row.branch}</strong>
          <span className={styles.branchKind}>{row.kind}</span>
        </div>
      ),
    },
    { id: "state", header: "状态", width: 88, render: (row) => <VStatusChip tone={stateTone(row.state)}>{row.stateLabel}</VStatusChip> },
    {
      id: "runtime",
      header: "运行",
      width: 168,
      render: (row) => (
        <div className={styles.runtimeCell}>
          <span className={styles.runtimeLine}>
            {row.backend !== "—" ? `后端 ${row.backend}` : "后端 —"} · {row.window}
          </span>
          <span className={styles.runtimeLine}>更新 {row.updated}</span>
        </div>
      ),
    },
    { id: "risk", header: "风险", width: 64, render: (row) => <VChip tone={RISK_TONE[row.risk]}>{RISK_LABEL[row.risk]}</VChip> },
    {
      id: "actions",
      header: "操作",
      width: 116,
      truncate: false,
      render: (row) => {
        const action = row.state === "stopped" ? "启动" : "停止";
        return (
          <div className={styles.rowActions}>
            <VButton variant="ghost" density="compact" onPress={() => setMockNotice(`（mock）已请求「打开」${row.branch}。本页不执行真实操作。`)}>
              打开
            </VButton>
            <VButton variant="ghost" density="compact" onPress={() => setMockNotice(`（mock）已请求「${action}」${row.branch}。本页不执行真实操作。`)}>
              {action}
            </VButton>
          </div>
        );
      },
    },
  ];

  return (
    <main data-launcher-layout-preview="true" className={styles.page}>
      <header className={styles.topbar}>
        <div>
          <p className={styles.eyebrow}>LAUNCHER · 隔离设计预览</p>
          <h1 className={styles.title}>分支实例</h1>
          <p className={styles.subtitle}>
            单一主数据面：状态页签 + 搜索与风险过滤，启动设置默认折叠为摘要。本页只使用 mock 数据，未连接生产 Launcher API。
          </p>
        </div>
        <div className={styles.topActions}>
          <span className={styles.mockBadge}>Mock-only · 未接入生产 API</span>
        </div>
      </header>

      <div className={styles.scenarioBar} aria-label="预览场景">
        <span className={styles.scenarioLabel}>预览场景</span>
        {(["running", "attention", "empty"] as ScenarioId[]).map((id) => (
          <VButton
            key={id}
            data-scenario={id}
            density="compact"
            variant={scenario === id ? "primary" : "secondary"}
            onPress={() => switchScenario(id)}
          >
            {SCENARIO_LABEL[id]}
          </VButton>
        ))}
      </div>

      <div className={styles.layout}>
        <section className={styles.main} aria-label="分支实例">
          <div className={styles.sectionHeader}>
            <div>
              <h2 className={styles.sectionTitle}>分支实例</h2>
              <p className={styles.sectionHint}>一行一个分支：状态、后端、窗口和操作</p>
            </div>
            <VStatusChip tone="success">Launcher 在线</VStatusChip>
          </div>

          <VTabs
            aria-label="分支实例状态"
            value={tab}
            onValueChange={(next) => setTab(next as TabId)}
            items={tabItems}
            className="mt-2"
            triggerClassName="whitespace-nowrap"
          />

          <div className={styles.toolbar}>
            <VInput
              aria-label="搜索分支"
              className={styles.search}
              placeholder="搜索分支或路径"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <VStringSelect
              ariaLabel="风险过滤"
              className={styles.riskSelect}
              value={risk}
              onValueChange={(next) => setRisk(next)}
              options={RISK_OPTIONS}
            />
            <span className={styles.rowCount}>{filtered.length} 条</span>
          </div>

          {isEmpty ? (
            <VEmptyState
              align="start"
              icon={<GitBranch size={22} aria-hidden="true" />}
              title="没有分支实例"
              actions={
                <VButton variant="secondary" density="compact" onPress={() => setMockNotice("（mock）已请求刷新分支实例列表。本页不执行真实请求。")}>
                  刷新（mock）
                </VButton>
              }
            >
              {scenario === "empty"
                ? "当前项目还没有任何分支实例。启动一个分支后，它会出现在这里。"
                : "没有匹配当前页签、搜索或风险过滤的分支实例。"}
            </VEmptyState>
          ) : (
            <VDenseTable
              ariaLabel="分支实例列表"
              resizable
              className="mt-3"
              columns={columns}
              rows={filtered}
              getRowKey={(row) => row.id}
              getRowState={(row) => ({
                tone: row.state === "running" ? "success" : row.state === "attention" ? "warning" : "neutral",
              })}
            />
          )}
        </section>

        <aside className={styles.rail} aria-label="设置与维护">
          <VSurface tone="panel" elevation="panel" padding="compact" className={styles.card}>
            <div className={styles.cardHeader}>
              <h3 className={styles.cardTitle}>启动设置</h3>
              <VButton
                data-startup-toggle
                variant="ghost"
                density="compact"
                aria-expanded={startupOpen}
                onPress={() => setStartupOpen((open) => !open)}
              >
                {startupOpen ? "收起" : "展开"}
              </VButton>
            </div>
            {startupOpen ? (
              <div data-startup-fields className={styles.settingsFields}>
                <label className={styles.field}>
                  运行档位
                  <VStringSelect ariaLabel="运行档位" value={profile} onValueChange={setProfile} options={PROFILE_OPTIONS} />
                </label>
                <label className={styles.field}>
                  后端端口
                  <VInput aria-label="后端端口" value={backendPort} onChange={(event) => setBackendPort(event.target.value)} />
                </label>
                <label className={styles.field}>
                  前端端口
                  <VInput aria-label="前端端口" value={frontendPort} onChange={(event) => setFrontendPort(event.target.value)} />
                </label>
                <label className={styles.field}>
                  窗口模式
                  <VStringSelect ariaLabel="窗口模式" value={windowMode} onValueChange={setWindowMode} options={WINDOW_MODE_OPTIONS} />
                </label>
                <label className={styles.field}>
                  窗口尺寸
                  <VStringSelect ariaLabel="窗口尺寸" value={windowSize} onValueChange={setWindowSize} options={WINDOW_SIZE_OPTIONS} />
                </label>
                <p className={styles.mockNote}>仅预览：字段不会保存或写入任何配置。</p>
              </div>
            ) : (
              <div data-startup-summary className={styles.summary}>
                <div className={styles.summaryRow}>
                  <span>运行档位</span>
                  <strong className={styles.summaryValue}>{profile}</strong>
                </div>
                <div className={styles.summaryRow}>
                  <span>后端</span>
                  <strong className={styles.summaryValue}>{backendPort}</strong>
                  <span>· 前端</span>
                  <strong className={styles.summaryValue}>{frontendPort}</strong>
                </div>
                <div className={styles.summaryRow}>
                  <span>窗口</span>
                  <strong className={styles.summaryValue}>{optionLabel(WINDOW_MODE_OPTIONS, windowMode)}</strong>
                  <span>· 尺寸</span>
                  <strong className={styles.summaryValue}>{optionLabel(WINDOW_SIZE_OPTIONS, windowSize)}</strong>
                </div>
              </div>
            )}
          </VSurface>

          <VSurface tone="inset" padding="compact" className={styles.card}>
            <div className={styles.cardHeader}>
              <h3 className={styles.cardTitle}>维护与诊断</h3>
              <VButton
                data-maintenance-toggle
                variant="ghost"
                density="compact"
                aria-expanded={maintenanceOpen}
                onPress={() => setMaintenanceOpen((open) => !open)}
              >
                {maintenanceOpen ? "收起" : "展开"}
              </VButton>
            </div>
            {maintenanceOpen ? (
              <div data-maintenance-fields className={styles.maintenanceRows}>
                {MAINTENANCE_ROWS.map(([key, value]) => (
                  <div key={key} className={styles.maintenanceRow}>
                    <span className={styles.maintenanceKey}>{key}</span>
                    <span className={styles.maintenanceValue}>{value}</span>
                  </div>
                ))}
                <p className={styles.mockNote}>仅预览：不会触发任何维护或诊断动作。</p>
              </div>
            ) : (
              <div data-maintenance-summary className={styles.summary}>
                <div className={styles.summaryRow}>
                  <span>维护档位</span>
                  <strong className={styles.summaryValue}>factory_runtime</strong>
                  <span>· 沙盒</span>
                  <strong className={styles.summaryValue}>关闭</strong>
                  <span>· 诊断</span>
                  <strong className={styles.summaryValue}>正常</strong>
                </div>
              </div>
            )}
          </VSurface>

          <VSurface tone="row" padding="compact" className={styles.card}>
            <p className={styles.mockNote}>
              隔离设计预览：纯 mock 数据，未连接生产 Launcher API，不调用生命周期接口，不读写任何配置。
            </p>
          </VSurface>
        </aside>
      </div>

      <footer className={styles.footer}>
        <span role="status" aria-live="polite">
          {mockNotice || "预览就绪 · 所有操作均为 mock"}
        </span>
      </footer>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <LauncherLayoutPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
