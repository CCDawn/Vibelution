/**
 * Isolated research-workflow toolbar preview.
 * Open: /research-workflow-toolbar-preview.html
 * Design acceptance only — does not change ResearchWorkflowToolbar.
 */
import { StrictMode, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import {
  VActionGroup,
  VButton,
  VSelect,
  VStatusChip,
  VToolbar,
  VuiProvider,
} from "../components/vui";
import "./base.css";
import "./tokens.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";
import "./research-workflow-toolbar-preview.css";
import { researchWorkflowToolbarPreviewStyles as styles } from "./research-workflow-toolbar-preview.styles";

type SceneId = "running" | "empty" | "waiting" | "longHypothesis";
type PanelId = "node" | "agents" | "timeline" | "team" | "progress" | "launch";

type ExperimentOption = {
  questionId: string;
  title: string;
  hypothesis: string;
  label: string;
  description: string;
};

type Scene = {
  id: SceneId;
  label: string;
  teamName: string;
  questionId: string | null;
  title: string;
  hypothesis: string;
  runStatus: string;
  stream: string;
  nextAction: string;
  completed: number;
  total: number;
  options: ExperimentOption[];
};

const SCI_TITLE = "Will the Navier-Stokes problem ever be solved?";
const LONG_HYPOTHESIS =
  "假说 hyp-sparse-gate：在相同数据、固定 seed=42 下引入稀疏预测误差门控，相比固定阈值基线降低 reconstruction_mse";

const EXPERIMENTS: ExperimentOption[] = [
  {
    questionId: "SCI-002",
    title: SCI_TITLE,
    hypothesis: "尚未选择假说",
    label: "SCI-002 · 资料寻找 · 0/16 · 准备中",
    description: SCI_TITLE,
  },
  {
    questionId: "SCI-096",
    title: "What are the coding principles embedded in neuronal spike trains?",
    hypothesis: "假说 hyp-a",
    label: "SCI-096 · 资料寻找 · 0/16 · 等待确认",
    description: "What are the coding principles embedded in neuronal spike trains?",
  },
];

const SCENES: Scene[] = [
  {
    id: "running",
    label: "进行中 · 截图同款",
    teamName: "挑战杯ai科研团队",
    questionId: "SCI-002",
    title: SCI_TITLE,
    hypothesis: "尚未选择假说",
    runStatus: "准备中",
    stream: "实时",
    nextAction: "资料寻找",
    completed: 0,
    total: 16,
    options: EXPERIMENTS,
  },
  {
    id: "waiting",
    label: "等待确认",
    teamName: "挑战杯ai科研团队",
    questionId: "SCI-096",
    title: "What are the coding principles embedded in neuronal spike trains?",
    hypothesis: "假说 hyp-a",
    runStatus: "等待确认",
    stream: "实时",
    nextAction: "资料寻找",
    completed: 3,
    total: 16,
    options: EXPERIMENTS,
  },
  {
    id: "longHypothesis",
    label: "超长假说",
    teamName: "挑战杯ai科研团队",
    questionId: "SCI-002",
    title: SCI_TITLE,
    hypothesis: LONG_HYPOTHESIS,
    runStatus: "运行中",
    stream: "实时",
    nextAction: "资料提炼",
    completed: 4,
    total: 16,
    options: [
      {
        questionId: "SCI-002",
        title: SCI_TITLE,
        hypothesis: LONG_HYPOTHESIS,
        label: "SCI-002 · 资料提炼 · 4/16 · 运行中",
        description: SCI_TITLE,
      },
      EXPERIMENTS[1],
    ],
  },
  {
    id: "empty",
    label: "尚未选择实验",
    teamName: "挑战杯ai科研团队",
    questionId: null,
    title: "",
    hypothesis: "",
    runStatus: "",
    stream: "",
    nextAction: "创建运行",
    completed: 0,
    total: 16,
    options: [],
  },
];

const PANELS: Array<{ id: PanelId; label: string }> = [
  { id: "agents", label: "Agent" },
  { id: "timeline", label: "时间线" },
  { id: "team", label: "团队" },
  { id: "progress", label: "题目进度" },
];

function hypothesisSwitchLabel(questionId: string, hypothesis: string): string {
  return `${questionId} · ${hypothesis.trim() || "尚未选择假说"}`;
}

function statusTone(status: string): "neutral" | "accent" | "warning" | "success" | "danger" {
  if (status === "等待确认") return "warning";
  if (status === "运行中") return "accent";
  if (status === "已完成") return "success";
  if (status === "运行失败") return "danger";
  return "neutral";
}

function patchSelectedHypothesis(scene: Scene, hypothesis: string): Scene {
  return {
    ...scene,
    hypothesis,
    options: scene.options.map((item) => (
      item.questionId === scene.questionId ? { ...item, hypothesis } : item
    )),
  };
}

function CurrentToolbar(props: {
  scene: Scene;
  panel: PanelId;
  onSelectExperiment: (questionId: string) => void;
  onOpenPanel: (panel: PanelId) => void;
}) {
  const { scene, panel } = props;
  return (
    <div className={styles.current} data-testid="current-toolbar">
      <div className={styles.currentContext}>
        <strong className={styles.currentPrimary}>{scene.teamName}</strong>
        {scene.questionId ? (
          <span className={styles.currentTruncated} title={`${scene.questionId} · ${scene.title}`}>
            {scene.questionId} · {scene.title}
          </span>
        ) : (
          <span className={styles.currentTruncated}>尚未选择实验</span>
        )}
        {scene.hypothesis ? <span className={styles.currentTruncated}>{scene.hypothesis}</span> : null}
        {scene.runStatus ? <span>{scene.runStatus}</span> : null}
        {scene.stream ? <span>{scene.stream}</span> : null}
        {scene.nextAction && scene.questionId ? (
          <VButton type="button" variant="ghost" density="compact" className={styles.currentNext}>
            {`下一步：${scene.nextAction}`}
          </VButton>
        ) : null}
      </div>
      <div className={styles.currentActions}>
        {scene.options.length > 0 ? (
          <VSelect
            density="compact"
            className={styles.currentSelect}
            aria-label="切换实验"
            placeholder="切换实验"
            selectedKey={scene.questionId}
            options={scene.options.map((item) => ({
              id: item.questionId,
              label: item.label,
              description: item.description,
            }))}
            onSelectionChange={(key) => {
              if (key == null) return;
              props.onSelectExperiment(String(key));
            }}
          />
        ) : null}
        {PANELS.map((item) => (
          <VButton
            key={item.id}
            type="button"
            density="compact"
            variant={panel === item.id ? "secondary" : "ghost"}
            onClick={() => props.onOpenPanel(item.id)}
          >
            {item.label}
          </VButton>
        ))}
        <VButton
          type="button"
          density="compact"
          variant={panel === "launch" ? "secondary" : "primary"}
          onClick={() => props.onOpenPanel("launch")}
        >
          {scene.questionId ? "新建运行" : "创建运行"}
        </VButton>
      </div>
    </div>
  );
}

function ProposedToolbar(props: {
  scene: Scene;
  panel: PanelId;
  slot?: string;
  onSelectExperiment: (questionId: string) => void;
  onOpenPanel: (panel: PanelId) => void;
}) {
  const { scene, panel, slot } = props;
  return (
    <VToolbar
      ariaLabel="科研流程"
      className={styles.proposed}
      data-testid={slot ? `proposed-toolbar-${slot}` : "proposed-toolbar"}
    >
      <div className={styles.proposedSwitcher} data-testid={slot ? `proposed-hypothesis-${slot}` : "proposed-hypothesis"}>
        {scene.options.length > 0 ? (
          <VSelect
            density="compact"
            aria-label="切换假说"
            placeholder="选择假说"
            selectedKey={scene.questionId}
            options={scene.options.map((item) => ({
              id: item.questionId,
              label: hypothesisSwitchLabel(item.questionId, item.hypothesis),
              description: item.title,
            }))}
            onSelectionChange={(key) => {
              if (key == null) return;
              props.onSelectExperiment(String(key));
            }}
          />
        ) : (
          <span className={styles.proposedEmpty}>
            尚未选择实验
          </span>
        )}
      </div>
      <div
        className={styles.proposedStatus}
        data-testid={slot ? `proposed-status-${slot}` : "proposed-status"}
      >
        <span className={styles.proposedStatusLabel}>状态</span>
        {scene.runStatus ? (
          <VStatusChip tone={statusTone(scene.runStatus)}>{scene.runStatus}</VStatusChip>
        ) : (
          <span className={styles.proposedStatusEmpty}>—</span>
        )}
      </div>
      <div className={styles.proposedActions}>
        <VActionGroup ariaLabel="工具面板" className={styles.proposedNav}>
          {PANELS.map((item) => (
            <VButton
              key={item.id}
              type="button"
              density="compact"
              variant={panel === item.id ? "secondary" : "ghost"}
              onClick={() => props.onOpenPanel(item.id)}
            >
              {item.label}
            </VButton>
          ))}
        </VActionGroup>
        <VButton
          type="button"
          density="compact"
          variant={panel === "launch" ? "secondary" : "primary"}
          data-testid={slot ? `proposed-cta-${slot}` : "proposed-cta"}
          onClick={() => props.onOpenPanel("launch")}
        >
          {scene.questionId ? "新建运行" : "创建运行"}
        </VButton>
      </div>
    </VToolbar>
  );
}

function WorkbenchFrame(props: {
  scene: Scene;
  panel: PanelId;
  narrow?: boolean;
  slot?: string;
  variant: "current" | "proposed";
  onSelectExperiment: (questionId: string) => void;
  onOpenPanel: (panel: PanelId) => void;
}) {
  const inspectorOpen = props.panel !== "node";
  const inspectorTitle = PANELS.find((item) => item.id === props.panel)?.label
    ?? (props.panel === "launch" ? (props.scene.questionId ? "新建运行" : "创建运行") : "节点");
  return (
    <div className={props.narrow ? styles.frameNarrow : styles.frame} data-variant={props.variant}>
      <aside className={styles.rail} aria-label="团队列表">
        <div className={styles.railItem}>AI 搜索范围团队</div>
        <div className={`${styles.railItem} ${styles.railItemActive}`}>{props.scene.teamName}</div>
      </aside>
      <div className={styles.main}>
        <div className={styles.strip}>
          {props.variant === "current" ? (
            <CurrentToolbar
              scene={props.scene}
              panel={props.panel}
              onSelectExperiment={props.onSelectExperiment}
              onOpenPanel={props.onOpenPanel}
            />
          ) : (
            <ProposedToolbar
              scene={props.scene}
              panel={props.panel}
              slot={props.slot}
              onSelectExperiment={props.onSelectExperiment}
              onOpenPanel={props.onOpenPanel}
            />
          )}
        </div>
        <div className={styles.canvas}>
          <p className={styles.canvasHint}>
            {props.variant === "current"
              ? "现在：换行后右侧空一截，题号和当前节点写了两遍。"
              : "建议：下拉选编号和假说，状态单独一列，左侧不再重复。"}
          </p>
          {inspectorOpen ? (
            <aside className={styles.inspector}>
              <h2 className={styles.inspectorTitle}>{inspectorTitle}</h2>
              <p className={styles.inspectorBody}>
                {props.scene.hypothesis
                  ? `完整赛题名在实验下拉里：${props.scene.title}`
                  : "检查器只在打开面板时出现。定位当前节点继续走画布控件。"}
              </p>
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ResearchWorkflowToolbarPreviewApp() {
  const [sceneId, setSceneId] = useState<SceneId>("running");
  const [panel, setPanel] = useState<PanelId>("node");
  const [overrideQuestionId, setOverrideQuestionId] = useState<string | null>(null);
  const baseScene = SCENES.find((item) => item.id === sceneId) ?? SCENES[0];
  const scene = useMemo(() => {
    if (!overrideQuestionId) return baseScene;
    const match = baseScene.options.find((item) => item.questionId === overrideQuestionId);
    if (!match) return baseScene;
    return {
      ...baseScene,
      questionId: match.questionId,
      title: match.title,
      hypothesis: match.hypothesis,
      nextAction: match.label.split(" · ")[1] || baseScene.nextAction,
      runStatus: match.label.split(" · ").at(-1) || baseScene.runStatus,
    };
  }, [baseScene, overrideQuestionId]);

  const selectExperiment = (questionId: string) => {
    setOverrideQuestionId(questionId);
  };
  const openPanel = (next: PanelId) => {
    setPanel((current) => (current === next ? "node" : next));
  };
  const pickScene = (id: SceneId) => {
    setSceneId(id);
    setOverrideQuestionId(null);
    setPanel("node");
  };

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>CHALLENGE CUP · TOOLBAR</p>
        <h1>科研流程上栏：单行三区</h1>
        <p className={styles.subtitle}>
          左侧不再单独写题号和假说。下拉负责选择编号和当前假说，状态单独成一列；节点进度留在画布上。
        </p>
        <div className={styles.scenes}>
          {SCENES.map((item) => (
            <VButton
              key={item.id}
              type="button"
              density="compact"
              variant={sceneId === item.id ? "secondary" : "ghost"}
              onClick={() => pickScene(item.id)}
            >
              {item.label}
            </VButton>
          ))}
        </div>
      </header>

      <div className={styles.compare}>
        <section className={styles.column} data-side="current">
          <div className={styles.columnLabel}>现在 · flex-wrap 半行</div>
          <WorkbenchFrame
            variant="current"
            scene={scene}
            panel={panel}
            onSelectExperiment={selectExperiment}
            onOpenPanel={openPanel}
          />
        </section>
        <section className={styles.column} data-side="proposed">
          <div className={styles.columnLabel}>建议 · 单行三区 · 宽屏</div>
          <WorkbenchFrame
            variant="proposed"
            scene={scene}
            panel={panel}
            onSelectExperiment={selectExperiment}
            onOpenPanel={openPanel}
          />
        </section>
        <section className={styles.column} data-side="stability">
          <div className={styles.columnLabel}>短假说 vs 长假说 · 右侧按钮应左右对齐</div>
          <WorkbenchFrame
            variant="proposed"
            slot="short"
            scene={patchSelectedHypothesis(SCENES[0], "假说 hyp-a")}
            panel="node"
            onSelectExperiment={selectExperiment}
            onOpenPanel={openPanel}
          />
          <WorkbenchFrame
            variant="proposed"
            slot="long"
            scene={patchSelectedHypothesis(SCENES[0], LONG_HYPOTHESIS)}
            panel="node"
            onSelectExperiment={selectExperiment}
            onOpenPanel={openPanel}
          />
        </section>
        <section className={styles.column} data-side="narrow">
          <div className={styles.columnLabel}>建议 · 720px 窄屏，横向轻滚而不是折行</div>
          <WorkbenchFrame
            variant="proposed"
            narrow
            scene={scene}
            panel={panel}
            onSelectExperiment={selectExperiment}
            onOpenPanel={openPanel}
          />
        </section>
      </div>

      <p className={styles.note}>
        预览只用假数据，没有接运行接口，也没有改正式 ResearchWorkflowToolbar。
        下拉闭合态显示「{scene.questionId ? hypothesisSwitchLabel(scene.questionId, scene.hypothesis) : "选择假说"}」，状态在旁边单独一列。
      </p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <ResearchWorkflowToolbarPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
