/**
 * Isolated preview for the approved three-pane research workflow IA.
 * Open: /research-process-workspace-preview.html
 * Preview-only mock data: no TeamsRoute, runtime API, or production workflow writes.
 */
import { StrictMode, useEffect, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import {
  VButton,
  VCanvasWorkbenchPage,
  VCheckbox,
  VNativeButton,
  VSelect,
  VStatusChip,
  VuiProvider,
} from "../components/vui";
import "./base.css";
import "./tokens.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";
import "./research-process-workspace-preview.css";
import { researchProcessWorkspacePreviewStyles as styles } from "./research-process-workspace-preview.styles";
import {
  PREVIEW_NODES,
  PREVIEW_PHASES,
  PREVIEW_SCENES,
  PREVIEW_VIEWPORTS,
  nodeTone,
  sceneById,
  type PreviewScene,
  type PreviewSceneId,
  type PreviewViewportId,
} from "./researchProcessWorkspacePreviewModel";

const HYPOTHESES = [
  "结构假说：异常扩散由局部边界条件触发",
  "机制假说：反馈延迟放大了短时波动",
  "反例假说：现有样本不足以排除测量偏差",
] as const;

function StageRail({ scene, onCurrentTask }: { scene: PreviewScene; onCurrentTask: () => void }) {
  const activePhase = PREVIEW_NODES.find((node) => node.id === scene.currentNodeId)?.phaseId;
  return (
    <nav className={styles.rail} aria-label="研究阶段" data-testid="stage-rail">
      <div className={styles.railCurrent}>
        <span className={styles.kicker}>当前任务</span>
        <strong>{scene.title}</strong>
        <span>{scene.progress}</span>
        <VButton variant="primary" density="compact" onPress={onCurrentTask}>回到当前任务</VButton>
      </div>
      <ol className={styles.phaseList}>
        {PREVIEW_PHASES.map((phase) => {
          const active = phase.id === activePhase;
          const activeIndex = PREVIEW_PHASES.findIndex((item) => item.id === activePhase);
          const phaseIndex = PREVIEW_PHASES.findIndex((item) => item.id === phase.id);
          return (
            <li key={phase.id} className={styles.phaseItem} data-active={active ? "true" : "false"}>
              <span className={styles.phaseIndex}>{phase.index}</span>
              <span className={styles.phaseCopy}>
                <strong>{phase.title}</strong>
                <small>{phase.description}</small>
              </span>
              <span className={styles.phaseMark} aria-label={active ? "当前阶段" : phaseIndex < activeIndex ? "已完成" : "未开始"}>
                {active ? "当前" : phaseIndex < activeIndex ? "✓" : "·"}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function WorkflowCanvas({
  scene,
  selectedNodeId,
  onSelectNode,
}: {
  scene: PreviewScene;
  selectedNodeId: string;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <section className={styles.canvas} aria-label="科研流程画布" data-testid="workflow-canvas">
      <div className={styles.canvasHeadline}>
        <div>
          <span className={styles.kicker}>SCI-004 · What causes anomalous diffusion?</span>
          <h2>{scene.phase}</h2>
        </div>
        <VStatusChip tone={scene.statusTone}>{scene.statusLabel}</VStatusChip>
      </div>
      <div className={styles.graph}>
        <svg className={styles.graphEdges} viewBox="0 0 1000 520" aria-hidden="true" preserveAspectRatio="none">
          <path d="M110 130 H350 H590 L810 280 H590 L330 400 H105" />
        </svg>
        {PREVIEW_NODES.map((node) => {
          const current = node.id === scene.currentNodeId;
          const selected = node.id === selectedNodeId;
          return (
            <VNativeButton
              key={node.id}
              type="button"
              className={styles.graphNode}
              style={{ left: `${node.x}%`, top: `${node.y}%` }}
              data-current={current ? "true" : "false"}
              data-selected={selected ? "true" : "false"}
              data-tone={nodeTone(node.id, scene)}
              data-testid={`workflow-node-${node.id}`}
              aria-label={`${node.title}${current ? "，当前任务" : selected ? "，正在查看" : ""}`}
              onClick={() => onSelectNode(node.id)}
            >
              <span className={styles.nodeTopline}>
                <strong>{node.title}</strong>
                {current ? <span>当前任务</span> : selected ? <span>正在查看</span> : null}
              </span>
              <small>{node.subtitle}</small>
            </VNativeButton>
          );
        })}
      </div>
      <div className={styles.canvasLegend}>
        <span><i data-tone="current" /> 当前任务</span>
        <span><i data-tone="selected" /> 正在查看</span>
        <span><i data-tone="done" /> 已完成</span>
      </div>
    </section>
  );
}

function InspectorActions({ scene }: { scene: PreviewScene }) {
  const [selected, setSelected] = useState(HYPOTHESES.map((_, index) => index));
  const isSelection = scene.id === "selection";
  return (
    <>
      {isSelection ? (
        <div className={styles.choiceList} data-testid="hypothesis-choice-list">
          {HYPOTHESES.map((hypothesis, index) => (
            <label key={hypothesis} className={styles.choiceRow}>
              <VCheckbox
                aria-label={`选择假说 ${index + 1}`}
                isSelected={selected.includes(index)}
                onChange={(next) => setSelected((current) => (
                  next ? [...new Set([...current, index])] : current.filter((item) => item !== index)
                ))}
              />
              <span>{hypothesis}</span>
            </label>
          ))}
        </div>
      ) : null}
      {scene.activity ? (
        <div className={styles.activity} role="status" aria-live="polite">
          <span className={styles.activityBar}><i /></span>
          <span>{scene.activity}</span>
        </div>
      ) : null}
      <div className={styles.expectation}>
        <span className={styles.kicker}>接下来会发生什么</span>
        <p>{scene.nextExpectation}</p>
      </div>
      {scene.disabledAction ? (
        <VButton
          className="w-full"
          variant="secondary"
          isDisabled={isSelection ? selected.length === 0 : true}
          disabledReason={scene.disabledReason}
        >
          {scene.disabledAction}
        </VButton>
      ) : null}
      {scene.primaryAction ? (
        <VButton
          className="w-full"
          variant="primary"
          isDisabled={isSelection && selected.length === 0}
          disabledReason={isSelection ? scene.disabledReason : undefined}
        >
          {scene.primaryAction}
        </VButton>
      ) : null}
      {scene.secondaryAction ? <VButton className="w-full" variant="secondary">{scene.secondaryAction}</VButton> : null}
    </>
  );
}

function TaskInspector({
  scene,
  selectedNodeId,
  onCurrentTask,
}: {
  scene: PreviewScene;
  selectedNodeId: string;
  onCurrentTask: () => void;
}) {
  const historical = selectedNodeId !== scene.currentNodeId;
  const selectedNode = PREVIEW_NODES.find((node) => node.id === selectedNodeId);
  return (
    <aside className={styles.inspector} aria-label="当前任务操作" data-testid="task-inspector">
      <header className={styles.inspectorHeader}>
        <span className={styles.kicker}>{historical ? "历史回顾 · 只读" : "当前任务 · 唯一操作面"}</span>
        <div className={styles.inspectorTitleRow}>
          <h2>{historical ? selectedNode?.title : scene.title}</h2>
          <VStatusChip tone={historical ? "neutral" : scene.statusTone}>{historical ? "只读" : scene.statusLabel}</VStatusChip>
        </div>
        <p>{historical ? `你正在查看“${selectedNode?.title}”的历史结果；当前任务仍是“${scene.title}”。` : scene.summary}</p>
      </header>
      <div className={styles.inspectorBody}>
        {historical ? (
          <>
            <div className={styles.historyCard}>
              <span className={styles.kicker}>历史结果</span>
              <strong>{selectedNode?.subtitle}</strong>
              <p>该节点已经归档。历史节点不会显示确认、重试或交接按钮。</p>
            </div>
            <VButton variant="primary" className="w-full" onPress={onCurrentTask}>返回当前任务</VButton>
          </>
        ) : <InspectorActions scene={scene} />}
      </div>
      {!historical && scene.primaryAction ? <div className={styles.stickyHint}>主操作固定在任务附近，不随长内容消失</div> : null}
    </aside>
  );
}

function ResearchArchive({ onReturn }: { onReturn: () => void }) {
  return (
    <section className={styles.archive} aria-label="科研档案" data-testid="research-archive">
      <header className={styles.archiveHeader}>
        <div>
          <span className={styles.kicker}>SCI-004 · 只读科研档案</span>
          <h2>异常扩散机理研究</h2>
          <p>题目、假说版本、评审结论、证据来源和交接记录集中在一个宽视图中。</p>
        </div>
        <VButton variant="primary" onPress={onReturn}>返回当前任务</VButton>
      </header>
      <div className={styles.archiveGrid}>
        <article><span className={styles.kicker}>当前结论</span><strong>保留 3 条假说</strong><p>第 1 轮评审识别出 4 个证据缺口。</p></article>
        <article><span className={styles.kicker}>证据来源</span><strong>12 条可追溯资料</strong><p>论文 7 · 数据集 3 · 反例记录 2</p></article>
        <article><span className={styles.kicker}>交接记录</span><strong>资料补充进行中</strong><p>2/4 个检索任务已完成，没有遗失结果。</p></article>
      </div>
      <div className={styles.archiveTimeline}>
        <h3>研究记录</h3>
        <ol>
          <li><strong>候选形成</strong><span>5 条候选经人工确认进入选择</span><time>09:18</time></li>
          <li><strong>假说选择</strong><span>3 条假说进入第 1 轮评审</span><time>09:24</time></li>
          <li><strong>团队评审</strong><span>保留结论并登记 4 个证据缺口</span><time>09:41</time></li>
          <li><strong>资料补充</strong><span>正在搜集，不需要人工启动</span><time>进行中</time></li>
        </ol>
      </div>
    </section>
  );
}

function ResponsiveOverlay({
  kind,
  open,
  onClose,
  children,
}: {
  kind: "rail" | "inspector";
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) closeRef.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className={styles.overlay} data-kind={kind} data-testid={`${kind}-drawer`}>
      <VNativeButton className={styles.overlayScrim} type="button" aria-label="关闭面板" onClick={onClose} />
      <div className={styles.overlayPanel} role="dialog" aria-modal="true" aria-label={kind === "rail" ? "研究阶段" : "当前任务操作"}>
        <VButton ref={closeRef} className={styles.overlayClose} variant="ghost" onPress={onClose}>关闭</VButton>
        {children}
      </div>
    </div>
  );
}

export function ResearchProcessWorkspacePreviewApp({
  initialSceneId = "review_processing",
  initialViewport = "desktop",
}: {
  initialSceneId?: PreviewSceneId;
  initialViewport?: PreviewViewportId;
} = {}) {
  const [sceneId, setSceneId] = useState<PreviewSceneId>(initialSceneId);
  const [viewport, setViewport] = useState<PreviewViewportId>(initialViewport);
  const scene = sceneById(sceneId);
  const [selectedNodeId, setSelectedNodeId] = useState(scene.currentNodeId);
  const [railOpen, setRailOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [lastDrawer, setLastDrawer] = useState<"rail" | "inspector" | null>(null);
  const railTriggerRef = useRef<HTMLButtonElement>(null);
  const inspectorTriggerRef = useRef<HTMLButtonElement>(null);
  const frameWidth = PREVIEW_VIEWPORTS.find((item) => item.id === viewport)?.width ?? 1440;
  const compactWorkspace = viewport !== "desktop";

  useEffect(() => {
    setSelectedNodeId(scene.currentNodeId);
    setRailOpen(false);
    setInspectorOpen(false);
  }, [scene.currentNodeId, scene.id]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || (!railOpen && !inspectorOpen)) return;
      event.preventDefault();
      setRailOpen(false);
      setInspectorOpen(false);
      (lastDrawer === "rail" ? railTriggerRef.current : inspectorTriggerRef.current)?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [inspectorOpen, lastDrawer, railOpen]);

  useEffect(() => {
    if (!railOpen && !inspectorOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [inspectorOpen, railOpen]);

  const showCurrentTask = () => {
    setSelectedNodeId(scene.currentNodeId);
    if (compactWorkspace) {
      setInspectorOpen(true);
      setLastDrawer("inspector");
    }
  };

  const toolbar = (
    <div className={styles.toolbar} data-testid="workspace-toolbar">
      <div className={styles.toolbarIdentity}>
        <strong>挑战杯 AI 科研团队</strong>
        <span>SCI-004 · 异常扩散机理</span>
      </div>
      <div className={styles.toolbarState}>
        <VStatusChip tone={scene.statusTone}>{scene.statusLabel}</VStatusChip>
        <span>{scene.progress}</span>
      </div>
      {compactWorkspace ? (
        <div className={styles.mobileActions}>
          <VButton ref={railTriggerRef} variant="secondary" onPress={() => {
            setRailOpen(true); setInspectorOpen(false); setLastDrawer("rail");
          }}>阶段</VButton>
          <VButton ref={inspectorTriggerRef} variant="primary" onPress={() => {
            setInspectorOpen(true); setRailOpen(false); setLastDrawer("inspector");
          }}>当前任务</VButton>
        </div>
      ) : null}
      <VButton variant="ghost" onPress={() => setSceneId(scene.archive ? "review_approval" : "archive")}>{scene.archive ? "返回流程" : "科研档案"}</VButton>
    </div>
  );

  const rail = <StageRail scene={scene} onCurrentTask={showCurrentTask} />;
  const inspector = <TaskInspector scene={scene} selectedNodeId={selectedNodeId} onCurrentTask={showCurrentTask} />;
  const canvas = scene.archive ? (
    <ResearchArchive onReturn={() => setSceneId("review_approval")} />
  ) : (
    <WorkflowCanvas scene={scene} selectedNodeId={selectedNodeId} onSelectNode={(nodeId) => {
      setSelectedNodeId(nodeId);
      if (compactWorkspace) {
        setInspectorOpen(true);
        setLastDrawer("inspector");
      }
    }} />
  );

  const frameContent = (
    <VCanvasWorkbenchPage
      ariaLabel="科研流程三栏工作台"
      title="科研流程"
      hideHeader
      toolbar={toolbar}
      rail={!compactWorkspace ? rail : undefined}
      canvas={canvas}
      inspector={!compactWorkspace && !scene.archive ? inspector : undefined}
      railClassName={styles.recipeRail}
      canvasClassName={styles.recipeCanvas}
      inspectorClassName={styles.recipeInspector}
      workspaceClassName={styles.recipeWorkspace}
      domainRecipe="research-workflow-current-task-preview"
    />
  );

  return (
    <main className={styles.page}>
      <header className={styles.previewHeader}>
        <div>
          <span className={styles.kicker}>ISOLATED DESIGN PREVIEW</span>
          <h1>科研流程三栏工作台</h1>
          <p>左侧只定位阶段，中间保持流程全貌，右侧只处理当前任务；所有区域由同一个 currentTask 驱动。</p>
        </div>
        <div className={styles.previewControls} aria-label="预览场景">
          <VSelect
            density="compact"
            aria-label="选择预览状态"
            selectedKey={sceneId}
            options={PREVIEW_SCENES.map((item) => ({ id: item.id, label: item.label, description: item.title }))}
            onSelectionChange={(key) => key != null && setSceneId(String(key) as PreviewSceneId)}
          />
          <div className={styles.viewportControls}>
            {PREVIEW_VIEWPORTS.map((item) => (
              <VButton key={item.id} variant={viewport === item.id ? "primary" : "secondary"} onPress={() => setViewport(item.id)}>{item.label}</VButton>
            ))}
          </div>
        </div>
      </header>

      <section
        className={styles.frame}
        style={{ ["--rpw-frame-width" as string]: `${frameWidth}px` }}
        data-viewport={viewport}
        data-testid="proposed-workspace-frame"
      >
        {frameContent}
        {compactWorkspace ? (
          <>
            <ResponsiveOverlay kind="rail" open={railOpen} onClose={() => setRailOpen(false)}>{rail}</ResponsiveOverlay>
            {!scene.archive ? <ResponsiveOverlay kind="inspector" open={inspectorOpen} onClose={() => setInspectorOpen(false)}>{inspector}</ResponsiveOverlay> : null}
          </>
        ) : null}
      </section>
      <p className={styles.previewNote}>安全 mock 数据；未连接真实运行时。请审查桌面、1024 和窄屏，以及“评审整理中 / 待确认 / 失败恢复 / 科研档案”等状态。</p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider><ResearchProcessWorkspacePreviewApp /></VuiProvider>
    </StrictMode>,
  );
}
