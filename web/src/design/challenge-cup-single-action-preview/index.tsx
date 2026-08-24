/**
 * Isolated interaction preview for the Challenge Cup single-action contract.
 * Open: /challenge-cup-single-action-preview.html
 * Safe mock data only: no Teams route, runtime API, or production mutation.
 */
import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Eye,
  History,
  LoaderCircle,
  LockKeyhole,
  Play,
  RotateCcw,
  Users,
} from "lucide-react";

import {
  VButton,
  VCanvasWorkbenchPage,
  VNativeButton,
  VNativeInput,
  VSelect,
  VStatusChip,
  VuiProvider,
} from "../../components/vui";
import "../base.css";
import "../tokens.css";
import "../tailwind.css";
import "../vui-provider-theme.css";
import "../vui-native-controls.css";
import "./preview.css";
import {
  ACTION_SCENES,
  GUARD_STATES,
  PREVIEW_VIEWPORTS,
  WORKFLOW_NODES,
  actionSceneById,
  type ActionScene,
  type ActionSceneId,
  type GuardStateId,
  type PreviewViewportId,
} from "./model";
import { singleActionPreviewStyles as styles } from "./styles";

const QUESTION_OPTIONS = [
  { id: "sci-002", label: "SCI-002 · Will the Navier–Stokes problem ever be solved?", description: "数学" },
  { id: "sci-003", label: "SCI-003 · Can materials self-repair under cyclic stress?", description: "材料科学" },
];

function Toolbar({ scene }: { scene: ActionScene }) {
  return (
    <header className={styles.toolbar} data-testid="product-toolbar">
      <div className={styles.toolbarIdentity}>
        <strong>挑战杯 AI 科研团队</strong>
        <span>SCI-002 · Navier–Stokes</span>
      </div>
      <div className={styles.toolbarContext}>
        <VStatusChip tone={scene.statusTone}>{scene.statusLabel}</VStatusChip>
        <span>画布只负责定位与回顾</span>
      </div>
      <nav className={styles.toolbarNav} aria-label="查看与协作导航">
        <VButton variant="ghost" icon={<Eye size={14} aria-hidden="true" />}>查看</VButton>
        <VButton variant="ghost" icon={<Users size={14} aria-hidden="true" />}>协作</VButton>
      </nav>
    </header>
  );
}

function WorkflowCanvas({
  scene,
  onSelectNode,
}: {
  scene: ActionScene;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <section className={styles.canvas} aria-label="科研流程画布" data-testid="workflow-canvas">
      <header className={styles.canvasHeader}>
        <div>
          <span className={styles.previewEyebrow}>科研流程 · 上下文面</span>
          <h2>从研究问题到实验交付</h2>
          <p>点历史节点只切换查看位置，不会改变右侧当前任务的写操作权威。</p>
        </div>
        <div className={styles.canvasLegend} aria-label="流程图例">
          <span><i data-tone="current" /> 当前任务</span>
          <span><i data-tone="selected" /> 正在查看</span>
          <span><i data-tone="done" /> 已完成</span>
        </div>
      </header>
      <div className={styles.canvasStage}>
        <svg className={styles.canvasEdges} viewBox="0 0 1000 560" preserveAspectRatio="none" aria-hidden="true">
          <path d="M120 150 H365 H650 Q790 150 790 305 V335 Q790 420 670 420 H470 H190" />
        </svg>
        {WORKFLOW_NODES.map((node) => {
          const current = node.id === scene.currentNodeId;
          const selected = node.id === scene.selectedNodeId;
          const currentIndex = WORKFLOW_NODES.findIndex((item) => item.id === scene.currentNodeId);
          const nodeIndex = WORKFLOW_NODES.findIndex((item) => item.id === node.id);
          const tone = current ? "current" : selected ? "selected" : nodeIndex < currentIndex ? "done" : "idle";
          return (
            <VNativeButton
              key={node.id}
              className={styles.canvasNode}
              style={{ left: `${node.x}%`, top: `${node.y}%` }}
              type="button"
              data-current={current ? "true" : "false"}
              data-selected={selected ? "true" : "false"}
              data-tone={tone}
              data-testid={`workflow-node-${node.id}`}
              aria-label={`${node.title}${current ? "，当前任务" : selected ? "，正在查看" : "，查看历史"}`}
              onClick={() => onSelectNode(node.id)}
            >
              <span className={styles.canvasNodeTop}>
                <strong>{node.title}</strong>
                {current ? <span>当前</span> : selected ? <span>查看</span> : null}
              </span>
              <small>{node.subtitle}</small>
            </VNativeButton>
          );
        })}
        <aside className={styles.canvasNote}>
          <LockKeyhole size={15} aria-hidden="true" />
          <span><strong>写操作已锁定到右栏</strong>画布、URL 与历史节点不会生成第二套动作。</span>
        </aside>
      </div>
    </section>
  );
}

function LaunchTask({
  limitsOpen,
  onLimitsOpenChange,
}: {
  limitsOpen: boolean;
  onLimitsOpenChange: (open: boolean) => void;
}) {
  const [questionId, setQuestionId] = useState("sci-002");
  return (
    <>
      <section className={styles.section} aria-labelledby="launch-question-title">
        <header className={styles.sectionHeader}>
          <span className={styles.previewEyebrow}>启动配置</span>
          <h3 id="launch-question-title">选择研究题目</h3>
        </header>
        <label className={styles.field}>
          <span>搜索题目</span>
          <VNativeInput placeholder="SCI-003 或 Riemann" aria-label="搜索题目" />
          <small className={styles.fieldHint}>题号、英文问题或学科</small>
        </label>
        <label className={styles.field}>
          <span>研究问题</span>
          <VSelect
            density="compact"
            aria-label="研究问题"
            selectedKey={questionId}
            options={QUESTION_OPTIONS}
            onSelectionChange={(key) => key != null && setQuestionId(String(key))}
          />
        </label>
        <article className={styles.questionCard}>
          <strong>SCI-002 · Will the Navier–Stokes problem ever be solved?</strong>
          <span>数学</span>
          <p>尚无运行记录；开始后会从资料寻找进入流程并保存 checkpoint。</p>
        </article>
      </section>
      <section className={styles.disclosure} data-testid="limit-disclosure">
        <div>
          <span className={styles.previewEyebrow}>运行安全上限</span>
          <strong>750,000 tokens</strong>
          <small>二阶段合计 · 6 小时 · 300 次调用 · 2 次重试</small>
        </div>
        <VButton
          variant="ghost"
          aria-expanded={limitsOpen}
          aria-controls="preview-limit-settings"
          trailingIcon={<ChevronDown size={14} aria-hidden="true" />}
          onPress={() => onLimitsOpenChange(!limitsOpen)}
        >
          调整上限
        </VButton>
      </section>
      {limitsOpen ? (
        <div id="preview-limit-settings" className={styles.disclosureBody}>
          <label className={styles.field}><span>Token 上限</span><VNativeInput defaultValue="750000" inputMode="numeric" /></label>
          <label className={styles.field}><span>最大调用</span><VNativeInput defaultValue="300" inputMode="numeric" /></label>
          <label className={styles.field}><span>失败重试</span><VNativeInput defaultValue="2" inputMode="numeric" /></label>
        </div>
      ) : null}
    </>
  );
}

function AwaitingTask() {
  return (
    <>
      <section className={styles.statusSurface} data-tone="warning">
        <CheckCircle2 className={styles.statusIcon} size={20} aria-hidden="true" />
        <div><strong>本轮结论已准备好</strong><p>确认只会冻结本轮结论，并把 4 个证据缺口交给资料补充。</p></div>
      </section>
      <div className={styles.factGrid}>
        <article className={styles.fact}><span>保留假说</span><strong>3</strong><small>候选共 5 条</small></article>
        <article className={styles.fact}><span>证据缺口</span><strong>4</strong><small>均已绑定假说</small></article>
        <article className={styles.fact}><span>评审轮次</span><strong>01</strong><small>13 条有效意见</small></article>
      </div>
      <section className={styles.section}>
        <header className={styles.sectionHeader}><span className={styles.previewEyebrow}>确认影响</span><h3>下一步自动进入资料补充</h3></header>
        <p>不会在画布、顶部工具条或历史档案中再出现另一个“继续”按钮。</p>
      </section>
    </>
  );
}

function RunningTask() {
  return (
    <>
      <section className={styles.statusSurface} data-tone="accent" role="status" aria-live="polite">
        <LoaderCircle className={styles.statusIcon} size={20} aria-hidden="true" />
        <div><strong>实验执行由系统接管</strong><p>正在运行第 2/5 个受控步骤；人工推进动作已隐藏。</p></div>
      </section>
      <div className={styles.progress}>
        <span><strong>42%</strong><small>预计剩余 38 分钟</small></span>
        <i className={styles.progressBar}><b style={{ width: "42%" }} /></i>
      </div>
      <div className={styles.factGrid}>
        <article className={styles.fact}><span>当前步骤</span><strong>02</strong><small>边界条件扫描</small></article>
        <article className={styles.fact}><span>Checkpoint</span><strong>5</strong><small>最近更新 1 分钟前</small></article>
      </div>
    </>
  );
}

function RecoveryTask() {
  return (
    <>
      <section className={styles.statusSurface} data-tone="danger">
        <RotateCcw className={styles.statusIcon} size={20} aria-hidden="true" />
        <div><strong>2 个来源需要重试</strong><p>恢复动作由正式运行快照决定，启动表单不会在此状态出现。</p></div>
      </section>
      <ul className={styles.recoveryList}>
        <li><CheckCircle2 size={16} aria-hidden="true" /><span><strong>5 条证据已保留</strong><small>不会重复采集或覆盖</small></span></li>
        <li><CircleDot size={16} aria-hidden="true" /><span><strong>2 个来源待恢复</strong><small>arXiv mirror · dataset registry</small></span></li>
        <li><History size={16} aria-hidden="true" /><span><strong>Checkpoint 完整</strong><small>恢复后从失败来源继续</small></span></li>
      </ul>
    </>
  );
}

function BlockedTask() {
  return (
    <>
      <section className={styles.statusSurface} data-tone="danger">
        <AlertTriangle className={styles.statusIcon} size={20} aria-hidden="true" />
        <div><strong>运行环境能力不足</strong><p>协议需要 GPU 隔离执行器，但当前环境只提供 CPU。重复启动无法恢复。</p></div>
      </section>
      <section className={styles.section}>
        <header className={styles.sectionHeader}><span className={styles.previewEyebrow}>解除方式</span><h3>先完成外部环境配置</h3></header>
        <p>环境满足要求后，右栏会基于新快照自动显示唯一可执行动作；当前不提供误导性的重试按钮。</p>
      </section>
    </>
  );
}

function HistoryTask() {
  return (
    <>
      <section className={styles.statusSurface} data-tone="neutral">
        <History className={styles.statusIcon} size={20} aria-hidden="true" />
        <div><strong>历史节点只读</strong><p>URL、画布选择和历史记录只决定看什么，不决定下一次写操作。</p></div>
      </section>
      <div className={styles.factGrid}>
        <article className={styles.fact}><span>题目版本</span><strong>v3</strong><small>2026-08-23 冻结</small></article>
        <article className={styles.fact}><span>引用资料</span><strong>12</strong><small>全部可追溯</small></article>
      </div>
      <section className={styles.section}>
        <header className={styles.sectionHeader}><span className={styles.previewEyebrow}>当前任务未改变</span><h3>资料补充需要处理</h3></header>
        <p>底部只提供“返回当前任务”，不会把历史节点变成新的启动入口。</p>
      </section>
    </>
  );
}

function GuardContent({ guard }: { guard: Exclude<GuardStateId, "ready"> }) {
  if (guard === "loading") {
    return (
      <section className={styles.guard} data-testid="guard-loading" role="status" aria-live="polite">
        <LoaderCircle size={22} aria-hidden="true" />
        <strong>正在同步正式运行快照</strong>
        <p>旧任务动作已清空；新状态确认前不会显示按钮。</p>
        <div className={styles.skeleton}><i /><i /><i /></div>
      </section>
    );
  }
  return (
    <section className={styles.guard} data-testid="guard-scope-mismatch" role="alert">
      <AlertTriangle size={22} aria-hidden="true" />
      <strong>当前查看范围与运行快照不一致</strong>
      <p>正在重新对齐 questionId、runId 与当前任务；旧动作保持隐藏。</p>
    </section>
  );
}

function SceneContent({
  scene,
  limitsOpen,
  onLimitsOpenChange,
}: {
  scene: ActionScene;
  limitsOpen: boolean;
  onLimitsOpenChange: (open: boolean) => void;
}) {
  if (scene.id === "not_started") return <LaunchTask limitsOpen={limitsOpen} onLimitsOpenChange={onLimitsOpenChange} />;
  if (scene.id === "awaiting_confirmation") return <AwaitingTask />;
  if (scene.id === "running") return <RunningTask />;
  if (scene.id === "recoverable") return <RecoveryTask />;
  if (scene.id === "blocked") return <BlockedTask />;
  return <HistoryTask />;
}

function CurrentTaskInspector({
  scene,
  guard,
  onReturnCurrent,
}: {
  scene: ActionScene;
  guard: GuardStateId;
  onReturnCurrent: () => void;
}) {
  const [limitsOpen, setLimitsOpen] = useState(false);
  const [otherOpen, setOtherOpen] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setLimitsOpen(false);
    setOtherOpen(false);
    setNotice("");
  }, [guard, scene.id]);

  const actionIcon = scene.id === "not_started"
    ? <Play size={15} aria-hidden="true" />
    : scene.id === "recoverable"
      ? <RotateCcw size={15} aria-hidden="true" />
      : scene.id === "history"
        ? <History size={15} aria-hidden="true" />
        : <CheckCircle2 size={15} aria-hidden="true" />;

  const runMockAction = () => {
    if (scene.id === "history") {
      onReturnCurrent();
      return;
    }
    setNotice(`已模拟“${scene.footerAction}”；预览未连接真实写接口。`);
  };

  return (
    <aside className={styles.inspector} aria-label="当前任务" data-testid="current-task-inspector">
      <header className={styles.inspectorHeader}>
        <div className={styles.inspectorMeta}>
          <span className={styles.previewEyebrow}>{guard === "ready" ? scene.eyebrow : "当前任务 · 同步保护"}</span>
          <VStatusChip tone={guard === "ready" ? scene.statusTone : "neutral"}>
            {guard === "ready" ? scene.statusLabel : guard === "loading" ? "同步中" : "范围待对齐"}
          </VStatusChip>
        </div>
        <div className={styles.inspectorTitle}>
          <h2>{guard === "ready" ? scene.title : guard === "loading" ? "正在确认当前任务" : "当前任务暂不可操作"}</h2>
        </div>
        <p className={styles.inspectorSummary}>
          {guard === "ready" ? scene.summary : "为避免旧按钮作用于新题目或新运行，写操作会先隐藏。"}
        </p>
        <div className={styles.authority}>
          <LockKeyhole size={13} aria-hidden="true" />
          <span>动作依据：{guard === "ready" ? scene.authority : "等待新的权威快照"}</span>
        </div>
      </header>

      <div className={styles.body}>
        {guard === "ready" ? (
          <SceneContent scene={scene} limitsOpen={limitsOpen} onLimitsOpenChange={setLimitsOpen} />
        ) : (
          <GuardContent guard={guard} />
        )}

        {guard === "ready" && scene.id !== "running" && scene.id !== "history" ? (
          <section className={styles.disclosure}>
            <div>
              <span className={styles.previewEyebrow}>低频路径</span>
              <strong>其他处理</strong>
              <small>查看原因、导出信息或请求协作</small>
            </div>
            <VButton
              variant="ghost"
              aria-expanded={otherOpen}
              aria-controls="preview-other-actions"
              trailingIcon={<ChevronDown size={14} aria-hidden="true" />}
              onPress={() => setOtherOpen(!otherOpen)}
            >
              {otherOpen ? "收起" : "展开"}
            </VButton>
          </section>
        ) : null}
        {guard === "ready" && otherOpen ? (
          <div id="preview-other-actions" className={styles.disclosureBody}>
            <p>低频、非主路径动作在真正执行前进入独立确认菜单，不与推进按钮并列。</p>
            <VButton variant="ghost">查看处理说明</VButton>
            <VButton variant="ghost">复制诊断摘要</VButton>
          </div>
        ) : null}
      </div>

      <footer className={styles.footer} data-action-count={guard === "ready" && scene.footerAction ? "1" : "0"}>
        <div className={styles.footerCopy} aria-live="polite">
          <span>{guard === "ready" ? scene.footerIdle : "操作已隐藏"}</span>
          <small>{guard === "ready" ? "右栏底部是唯一流程推进位置" : "同步完成后只显示新任务允许的动作"}</small>
        </div>
        {guard === "ready" && scene.footerAction ? (
          <VButton
            className={styles.footerAction}
            variant={scene.footerActionKind === "navigation" ? "secondary" : "primary"}
            icon={actionIcon}
            data-footer-action="true"
            data-progress-action={scene.footerActionKind === "progress" ? "true" : "false"}
            onPress={runMockAction}
          >
            {scene.footerAction}
          </VButton>
        ) : null}
      </footer>
      {notice ? <div className={styles.toast} role="status">{notice}</div> : null}
    </aside>
  );
}

export function ChallengeCupSingleActionPreviewApp({
  initialSceneId = "recoverable",
  initialGuard = "ready",
  initialViewport = "desktop",
}: {
  initialSceneId?: ActionSceneId;
  initialGuard?: GuardStateId;
  initialViewport?: PreviewViewportId;
} = {}) {
  const [sceneId, setSceneId] = useState<ActionSceneId>(initialSceneId);
  const [guard, setGuard] = useState<GuardStateId>(initialGuard);
  const [viewport, setViewport] = useState<PreviewViewportId>(initialViewport);
  const [returnSceneId, setReturnSceneId] = useState<ActionSceneId>(initialSceneId === "history" ? "recoverable" : initialSceneId);
  const scene = actionSceneById(sceneId);
  const frameWidth = PREVIEW_VIEWPORTS.find((item) => item.id === viewport)?.width ?? 1440;

  const selectScene = (next: ActionSceneId) => {
    if (next !== "history") setReturnSceneId(next);
    setSceneId(next);
  };

  const selectNode = (nodeId: string) => {
    if (nodeId === scene.currentNodeId) return;
    if (scene.id !== "history") setReturnSceneId(scene.id);
    setSceneId("history");
  };

  const returnCurrent = () => setSceneId(returnSceneId === "history" ? "recoverable" : returnSceneId);
  const toolbar = useMemo(() => <Toolbar scene={scene} />, [scene]);
  const inspector = <CurrentTaskInspector scene={scene} guard={guard} onReturnCurrent={returnCurrent} />;
  const canvas = <WorkflowCanvas scene={scene} onSelectNode={selectNode} />;

  return (
    <main className={styles.page} data-theme="light">
      <header className={styles.previewHeader}>
        <div className={styles.previewIntro}>
          <span className={styles.previewEyebrow}>ISOLATED INTERACTION PREVIEW · 安全 MOCK</span>
          <h1>右栏单一推进按钮</h1>
          <p>先决定当前权威任务，再决定唯一按钮；历史、画布和 URL 只负责查看。</p>
        </div>
        <div className={styles.previewControls} aria-label="预览控制，不属于产品界面">
          <label className={styles.controlGroup}>
            <span>任务状态</span>
            <VSelect
              density="compact"
              aria-label="选择任务状态"
              selectedKey={sceneId}
              options={ACTION_SCENES.map((item) => ({ id: item.id, label: item.label, description: item.title }))}
              onSelectionChange={(key) => key != null && selectScene(String(key) as ActionSceneId)}
            />
          </label>
          <label className={styles.controlGroup}>
            <span>同步保护</span>
            <VSelect
              density="compact"
              aria-label="选择同步保护状态"
              selectedKey={guard}
              options={GUARD_STATES}
              onSelectionChange={(key) => key != null && setGuard(String(key) as GuardStateId)}
            />
          </label>
          <div className={styles.viewportGroup} aria-label="预览视口">
            {PREVIEW_VIEWPORTS.map((item) => (
              <VButton key={item.id} variant={viewport === item.id ? "primary" : "secondary"} onPress={() => setViewport(item.id)}>
                {item.label}
              </VButton>
            ))}
          </div>
        </div>
      </header>

      <section
        className={styles.frame}
        style={{ ["--sao-frame-width" as string]: `${frameWidth}px` }}
        data-viewport={viewport}
        data-testid="single-action-preview-frame"
      >
        <VCanvasWorkbenchPage
          ariaLabel="挑战杯科研流程单一操作预览"
          title="科研流程"
          hideHeader
          toolbar={toolbar}
          canvas={viewport === "mobile" ? inspector : canvas}
          inspector={viewport === "mobile" ? undefined : inspector}
          canvasClassName={styles.recipeCanvas}
          inspectorClassName={styles.recipeInspector}
          workspaceClassName={styles.recipeWorkspace}
          domainRecipe="challenge-cup-single-action-preview"
        />
      </section>
      <p className={styles.previewNote}>预览只验证信息层级、状态切换和按钮数量；不连接真实题目、运行时或写接口，也不代表正式 UI 已修改。</p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider><ChallengeCupSingleActionPreviewApp /></VuiProvider>
    </StrictMode>,
  );
}
