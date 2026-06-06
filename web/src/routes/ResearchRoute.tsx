import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  BookOpenCheck,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  FileSearch,
  FlaskConical,
  GitBranch,
  Layers3,
  ArrowDown,
  LoaderCircle,
  RefreshCw,
  SearchCheck,
  Sparkles,
  Target,
  Pause,
  Play,
  Trash2,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ResearchCandidateTheme,
  ResearchDiscoverySessionList,
  ResearchDiscoverySessionPayload,
  ResearchFlowCanvas,
  ResearchFlowExecutionResponse,
  ResearchFlowNode,
  ResearchSource,
  ResearchThemeCard,
} from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./ResearchRoute.module.css";

type DraftInput = {
  openGoal: string;
  constraints: string;
  preferences: string;
};

type ResearchStageKey = "broad" | "deep" | "evidence" | "themes" | "card";
type ResearchWorkflowMode = "manual" | "auto";

type FlowStageItem = {
  node: ResearchFlowNode;
  stage: ResearchStageKey;
};

const PREVIOUS_DEFAULT_INPUT = {
  zh: {
    openGoal: "找一个计算机相关、适合 AI Scientist 赛题的新颖交叉学科研究主题。",
    constraints: "学生团队可做；能基于公开论文、GitHub、数据集或网页资料进行初步验证；适合比赛 MVP 展示。",
    preferences: "更偏新颖；优先问题视角创新，其次方法迁移、学科组合、应用场景；避免普通 RAG 或文献综述工具。",
  },
  en: {
    openGoal: "Find a novel interdisciplinary research theme related to computer science for the AI Scientist topic.",
    constraints:
      "Suitable for a student team; grounded in public papers, GitHub, datasets, or web sources; suitable for a competition MVP.",
    preferences:
      "Novelty first; prioritize problem-perspective novelty, then method transfer, discipline combination, and application scenario; avoid generic RAG or literature-review tools.",
  },
} as const;

const COPY = {
  zh: {
    eyebrow: "AI Scientist Theme Discovery",
    subtitle: "从开放目标出发，联网调研并发现新颖性优先的候选科研主题。",
    create: "创建会话",
    deleteSession: "删除会话",
    deleteSessionConfirm: "确定删除这个科研会话吗？这会移除该会话下的检索、证据、候选主题和主题卡记录。",
    runDraft: "一键草稿",
    pause: "暂停",
    pausing: "暂停中",
    start: "开始",
    running: "运行中",
    complete: "完成",
    ready: "等待",
    failed: "失败",
    workflowMode: "流程模式",
    manualMode: "手动",
    autoMode: "自动",
    continueWorkflow: "继续下一步",
    evidenceRequests: "缺失证据请求",
    confirmEvidenceSearch: "确认补搜",
    broad: "广撒网",
    deep: "定向深搜",
    evidence: "抽取证据",
    themes: "生成主题",
    select: "选择",
    themeCard: "主题卡",
    candidateCardPreview: "候选卡预览",
    formalCard: "正式主题卡",
    previewBeforeCard: "先从候选主题中选择一个方向，确认后再生成正式主题卡。",
    collapseTrace: "收起过程",
    expandTrace: "展开过程",
    approve: "批准",
    rerun: "重跑",
    history: "研究会话",
    intake: "选题发现入口",
    openGoal: "开放目标",
    constraints: "约束条件",
    preferences: "偏好",
    candidates: "候选主题",
    sources: "来源与证据",
    workflow: "流程条",
    prompts: "提示词",
    promptCenter: "Agent 提示词中心",
    researchView: "科研",
    agentTemplate: "Agent 模板",
    llmConfig: "模型绑定",
    agentTemplateConfig: "Agent 绑定配置",
    agentTemplateSaved: "Agent 绑定已保存",
    llmConfigMissing: "未找到对应模型绑定",
    selectedCard: "概念级主题卡",
    agentReview: "Agent 自评",
    agentReport: "Agent 调研报告",
    agentMode: "真实网络状态",
    liveNetwork: "真实联网",
    noFailures: "暂无失败调用",
    latestQueries: "最近查询",
    observations: "观察结论",
    warnings: "风险提示",
    providerFailures: "Provider 失败",
    noSession: "还没有主题发现会话。先输入目标和约束，再创建会话。",
    emptyCandidates: "运行一键草稿或分阶段动作后，这里会出现 5 个候选主题。",
    emptyCard: "选择一个主题后，可以生成概念级主题卡。",
    saved: "已保存",
    stale: "需复核",
    selected: "已选择",
    shortlisted: "候选",
    draft: "草稿",
    approved: "已批准",
    searchRuns: "检索轮次",
    sourceCount: "来源",
    evidenceCount: "证据",
    themeCount: "主题",
    staleCount: "过期",
    cardCount: "主题卡",
    score: "推荐分",
    novelty: "新颖路径",
    competition: "扣题度",
    data: "数据线索",
    risk: "不确定性",
    boundary: "边界",
    boundaryBody: "第一版只做主题发现与概念主题卡，不执行实验、不交接监督进化、不修改 baseline。",
    defaultInput: {
      openGoal:
        "围绕 XH-202619「基于国产开源大模型的 AI Scientist 的研发与应用」，发现一个计算机与具体学科交叉的高质量研究主题，并让 Vibelution 作为 AI Scientist 平台完成从资料输入到可验证科学假设与研究计划输出的闭环。",
      constraints:
        "赛题硬约束：必须基于国产开源大模型，重点使用 Qwen/千问系列；模型调用需可通过阿里云百炼平台说明或截图证明；系统形态应是超级智能体或多智能体架构，具备问题理解、知识整合、关联发现、可验证假设生成能力。\n\n科研闭环要求：输入可以是公开论文、GitHub 项目、开放数据集、网页资料或学科问题集；输出必须能形成《科学假设与研究计划》，至少覆盖待研究问题 Problem Statement、解决思路 Rationale、技术手段 Technical Details、数据集 Datasets（Source/Target）、论文标题、摘要、方法论 Methods、实验设计 Experiments、基线 Baselines、评估指标 Metrics、初步结果 Results、真实参考文献 References。\n\n参赛可行性：学生团队可在 2026 年 9 月 5 日前形成 MVP；技术方案文档不超过 20 页；需要核心代码、上下文工程/agent 工作流、真实案例；鼓励交互式前端和 10 分钟内演示视频。",
      preferences:
        "优先新颖、可验证、扣题的上游科研主题：让 AI Scientist 发现知识缺口、提出可证伪假设、设计实验、评估结果并反思迭代，而不是普通 RAG、文献综述或展示型应用。\n\n主题选择优先级：1. 核心假设创新且自洽；2. 有真实数据和可落地验证路径；3. 能体现多智能体协作或超级智能体 Skills；4. 能处理科学模态数据或跨学科证据；5. 对 Vibelution agent 能力有明确提升，例如检索、证据审查、假设生成、实验设计、代码改进、评估闭环。\n\n评分对齐：科学价值 40 分、技术深度 30 分、应用潜力 30 分；避免虚构引用、不可复现数据、泛泛 AI+X、没有实验指标的概念包装。",
    },
  },
  en: {
    eyebrow: "AI Scientist Theme Discovery",
    subtitle: "Start from an open goal, search public sources, and find novelty-first research themes.",
    create: "Create session",
    deleteSession: "Delete session",
    deleteSessionConfirm: "Delete this research session? This removes its search runs, evidence, candidate themes, and theme cards.",
    runDraft: "Run draft",
    pause: "Pause",
    pausing: "Pausing",
    start: "Start",
    running: "Running",
    complete: "Complete",
    ready: "Ready",
    failed: "Failed",
    workflowMode: "Workflow mode",
    manualMode: "Manual",
    autoMode: "Auto",
    continueWorkflow: "Continue",
    evidenceRequests: "Missing evidence",
    confirmEvidenceSearch: "Confirm search",
    broad: "Broad search",
    deep: "Deep search",
    evidence: "Extract evidence",
    themes: "Generate themes",
    select: "Select",
    themeCard: "Theme card",
    candidateCardPreview: "Candidate card preview",
    formalCard: "Formal theme card",
    previewBeforeCard: "Choose a candidate theme first, then generate its formal theme card.",
    collapseTrace: "Collapse trace",
    expandTrace: "Expand trace",
    approve: "Approve",
    rerun: "Rerun",
    history: "Research sessions",
    intake: "Discovery intake",
    openGoal: "Open goal",
    constraints: "Constraints",
    preferences: "Preferences",
    candidates: "Candidate themes",
    sources: "Sources and evidence",
    workflow: "Workflow rail",
    prompts: "Prompts",
    promptCenter: "Agent prompt center",
    researchView: "Research",
    agentTemplate: "Agent template",
    llmConfig: "LLM config",
    agentTemplateConfig: "Agent binding config",
    agentTemplateSaved: "Agent binding saved",
    llmConfigMissing: "LLM config not found",
    selectedCard: "Concept theme card",
    agentReview: "Agent review",
    agentReport: "Agent research report",
    agentMode: "Live-search state",
    liveNetwork: "Live network",
    noFailures: "No failed provider calls",
    latestQueries: "Latest queries",
    observations: "Observations",
    warnings: "Warnings",
    providerFailures: "Provider failures",
    noSession: "No theme discovery session yet. Enter a goal and constraints, then create one.",
    emptyCandidates: "Run draft or staged actions to generate five candidate themes here.",
    emptyCard: "Select a theme, then generate its concept-level theme card.",
    saved: "Saved",
    stale: "Stale",
    selected: "Selected",
    shortlisted: "Shortlisted",
    draft: "Draft",
    approved: "Approved",
    searchRuns: "Search runs",
    sourceCount: "Sources",
    evidenceCount: "Evidence",
    themeCount: "Themes",
    staleCount: "Stale",
    cardCount: "Cards",
    score: "Score",
    novelty: "Novelty path",
    competition: "Competition fit",
    data: "Dataset clues",
    risk: "Uncertainty",
    boundary: "Boundary",
    boundaryBody:
      "The first release only discovers themes and concept cards. It does not run experiments, hand off to Supervised Evolution, or mutate baseline behavior.",
    defaultInput: {
      openGoal:
        "For XH-202619, develop a novel computer-science-plus-domain research theme where Vibelution acts as an AI Scientist platform and closes the loop from source input to verifiable scientific hypothesis and research plan output.",
      constraints:
        "Competition constraints: use a domestic open-source foundation model, especially Qwen; model calls should be explainable through Alibaba Cloud Bailian evidence or screenshots; the system should be a super-agent or multi-agent architecture with problem understanding, knowledge integration, association discovery, and verifiable hypothesis generation.\n\nResearch-plan output must cover Problem Statement, Rationale, Technical Details, Datasets with Source and Target, Paper Title, Paper Abstract, Methods, Experiments, Baselines, Metrics, Results, and real References. Inputs may include public papers, GitHub projects, open datasets, web sources, or published scientific question sets.\n\nFeasibility constraints: a student team should be able to build an MVP before September 5, 2026; the final package should support a PDF technical plan within 20 pages, core code, context-engineering or agent-workflow code, a real case study, and optionally an interactive frontend plus a demo video under 10 minutes.",
      preferences:
        "Prioritize upstream scientific research themes where the AI Scientist identifies knowledge gaps, proposes falsifiable hypotheses, designs experiments, evaluates results, and iterates. Avoid generic RAG, literature-review tools, or display-only applications.\n\nSelection priority: innovative and self-consistent core hypothesis; real data and feasible validation path; visible multi-agent or super-agent design; scientific-modal or interdisciplinary evidence handling; explicit improvement to Vibelution agent capabilities such as retrieval, evidence review, hypothesis generation, experiment design, code improvement, and evaluation loops.\n\nAlign with judging: scientific value 40, technical depth 30, application potential 30. Reject hallucinated references, unreproducible datasets, generic AI+X framing, and concepts without experimental metrics.",
    },
  },
};

const STAGES = [
  { id: "broad", icon: SearchCheck },
  { id: "deep", icon: Target },
  { id: "evidence", icon: BookOpenCheck },
  { id: "themes", icon: BrainCircuit },
  { id: "card", icon: BadgeCheck },
] as const;

const AUTO_DRAFT_STEPS = [
  { stage: "broad", suffix: "run-broad-search" },
  { stage: "deep", suffix: "run-deep-search" },
  { stage: "evidence", suffix: "extract-evidence" },
  { stage: "themes", suffix: "generate-themes" },
] as const;

export function ResearchRoute() {
  const { lang, t } = useAppI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const [activeSessionId, setActiveSessionId] = useState("");
  const [activeStage, setActiveStage] = useState<ResearchStageKey>("broad");
  const [activeFlowNodeId, setActiveFlowNodeId] = useState("");
  const [runningFlowNodeId, setRunningFlowNodeId] = useState("");
  const [runningStage, setRunningStage] = useState<ResearchStageKey | "draft" | "">("");
  const [workflowMode, setWorkflowMode] = useState<ResearchWorkflowMode>("manual");
  const [autoDraftPauseRequested, setAutoDraftPauseRequested] = useState(false);
  const [draft, setDraft] = useState<DraftInput>(copy.defaultInput);
  const autoDraftPauseRequestedRef = useRef(false);

  useEffect(() => {
    setDraft((current) => ({
      openGoal: shouldRefreshDefaultDraft(current.openGoal, "openGoal", lang)
        ? copy.defaultInput.openGoal
        : current.openGoal,
      constraints: shouldRefreshDefaultDraft(current.constraints, "constraints", lang)
        ? copy.defaultInput.constraints
        : current.constraints,
      preferences: shouldRefreshDefaultDraft(current.preferences, "preferences", lang)
        ? copy.defaultInput.preferences
        : current.preferences,
    }));
  }, [copy.defaultInput.constraints, copy.defaultInput.openGoal, copy.defaultInput.preferences, lang]);

  const sessionsQuery = useQuery({
    queryKey: queryKeys.researchThemeDiscoverySessions(),
    queryFn: () => fetchJson<ResearchDiscoverySessionList>("/api/research/theme-discovery/sessions"),
  });

  const sessions = sessionsQuery.data?.sessions ?? [];

  useEffect(() => {
    if (!activeSessionId && sessions[0]?.sessionId) {
      setActiveSessionId(sessions[0].sessionId);
    }
  }, [activeSessionId, sessions]);

  const sessionQuery = useQuery({
    queryKey: queryKeys.researchThemeDiscoverySession(activeSessionId),
    queryFn: () =>
      fetchJson<ResearchDiscoverySessionPayload>(
        `/api/research/theme-discovery/sessions/${encodeURIComponent(activeSessionId)}`,
      ),
    enabled: Boolean(activeSessionId),
    refetchInterval: runningStage ? 1200 : false,
  });

  const active = sessionQuery.data;
  const flowCanvasQuery = useQuery({
    queryKey: queryKeys.researchFlowCanvas(),
    queryFn: () => fetchJson<ResearchFlowCanvas>("/api/research/flow-canvas"),
    refetchInterval: runningStage ? 1200 : false,
  });

  const currentThemes = useMemo(
    () =>
      [...(active?.candidateThemes ?? [])].sort((left, right) => right.recommendationScore - left.recommendationScore),
    [active?.candidateThemes],
  );
  const selectedTheme = useMemo(
    () =>
      currentThemes.find((theme) => theme.themeId === active?.session.selectedThemeId) ??
      currentThemes.find((theme) => theme.status === "selected") ??
      currentThemes[0],
    [active?.session.selectedThemeId, currentThemes],
  );
  const selectedCard = useMemo(() => latestThemeCard(active?.themeCards ?? [], selectedTheme?.themeId), [
    active?.themeCards,
    selectedTheme?.themeId,
  ]);
  const missingEvidenceRequests = useMemo(() => latestMissingEvidenceRequests(active), [active]);
  const flowStageItems = useMemo(
    () => (flowCanvasQuery.data?.nodes ?? []).map((node) => ({ node, stage: flowNodeStage(node) })),
    [flowCanvasQuery.data?.nodes],
  );
  const activeFlowItem =
    flowStageItems.find((item) => item.node.id === activeFlowNodeId) ??
    flowStageItems.find((item) => item.stage === activeStage) ??
    flowStageItems[0];
  const effectiveStage = activeFlowItem?.stage ?? activeStage;
  const nextFlowNode = useMemo(
    () => nextRunnableFlowNode(flowCanvasQuery.data?.nodes ?? []),
    [flowCanvasQuery.data?.nodes],
  );

  useEffect(() => {
    if (!flowStageItems.length) {
      return;
    }
    const current = flowStageItems.find((item) => item.node.id === activeFlowNodeId);
    if (current) {
      setActiveStage(current.stage);
      return;
    }
    const next = flowStageItems[0];
    setActiveFlowNodeId(next.node.id);
    setActiveStage(next.stage);
  }, [activeFlowNodeId, flowStageItems]);

  const invalidateResearch = async (sessionId?: string) => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySessions() });
    await queryClient.invalidateQueries({ queryKey: queryKeys.researchFlowCanvas() });
    if (sessionId || activeSessionId) {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.researchThemeDiscoverySession(sessionId || activeSessionId),
      });
    }
  };

  const createMutation = useMutation({
    mutationFn: () =>
      fetchJson<ResearchDiscoverySessionPayload>("/api/research/theme-discovery/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...draft, candidateCount: 5 }),
    }),
    onSuccess: async (payload) => {
      setActiveSessionId(payload.session.sessionId);
      setActiveStage("broad");
      await invalidateResearch(payload.session.sessionId);
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) =>
      fetchJson<ResearchDiscoverySessionList & { deleted: boolean; sessionId: string }>(
        `/api/research/theme-discovery/sessions/${encodeURIComponent(sessionId)}`,
        {
          method: "DELETE",
        },
      ),
    onSuccess: async (payload) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySessions() });
      queryClient.removeQueries({ queryKey: queryKeys.researchThemeDiscoverySession(payload.sessionId) });
      const nextSessionId = payload.sessions[0]?.sessionId ?? "";
      setActiveSessionId((current) => (current === payload.sessionId ? nextSessionId : current));
    },
  });

  const actionMutation = useMutation({
    mutationFn: ({ endpoint, body }: { endpoint: string; body?: unknown }) =>
      fetchJson<ResearchDiscoverySessionPayload>(endpoint, {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      }),
    onSuccess: async (payload) => {
      setActiveSessionId(payload.session.sessionId);
      await invalidateResearch(payload.session.sessionId);
    },
    onSettled: () => {
      setRunningStage("");
    },
  });

  const flowExecuteMutation = useMutation({
    mutationFn: ({ nodeId }: { nodeId?: string }) =>
      fetchJson<ResearchFlowExecutionResponse>("/api/research/flow-canvas/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: activeSessionId, nodeId }),
      }),
    onSuccess: async (result) => {
      const executedNode = result.canvas.nodes.find((node) => node.id === result.execution.nodeId);
      setActiveSessionId(result.execution.sessionId);
      setActiveFlowNodeId(result.execution.nodeId);
      setActiveStage(flowNodeStage(executedNode));
      await invalidateResearch(result.execution.sessionId);
    },
    onSettled: () => {
      setRunningFlowNodeId("");
      setRunningStage("");
    },
  });

  const autoDraftMutation = useMutation({
    mutationFn: async ({
      initialPayload,
      sessionId,
      startIndex,
    }: {
      initialPayload?: ResearchDiscoverySessionPayload;
      sessionId: string;
      startIndex: number;
    }) => {
      autoDraftPauseRequestedRef.current = false;
      setAutoDraftPauseRequested(false);
      let latestPayload: ResearchDiscoverySessionPayload | null = initialPayload ?? null;
      let completedEvidenceSupplement = Boolean(
        latestPayload &&
          latestMissingEvidenceRequests(latestPayload).length &&
          latestEvidenceIsOlderThanDeepSearch(latestPayload),
      );
      const runAutoStep = async (stage: ResearchStageKey, suffix: string, body?: unknown) => {
        setActiveStage(stage);
        setRunningStage(stage);
        void queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySession(sessionId) });
        const payload = await fetchJson<ResearchDiscoverySessionPayload>(
          `/api/research/theme-discovery/sessions/${encodeURIComponent(sessionId)}/${suffix}`,
          {
            method: "POST",
            headers: body ? { "Content-Type": "application/json" } : undefined,
            body: body ? JSON.stringify(body) : undefined,
          },
        );
        setActiveSessionId(payload.session.sessionId);
        await invalidateResearch(payload.session.sessionId);
        return payload;
      };
      if (latestPayload && startIndex >= autoDraftStepIndex("themes")) {
        const requests = latestMissingEvidenceRequests(latestPayload);
        if (requests.length && !hasDeepSearchAfterLatestEvidence(latestPayload)) {
          completedEvidenceSupplement = true;
          latestPayload = await runAutoStep("deep", "run-deep-search", { evidenceRequests: requests });
          if (!autoDraftPauseRequestedRef.current) {
            latestPayload = await runAutoStep("evidence", "extract-evidence");
          }
        } else if (requests.length && latestEvidenceIsOlderThanDeepSearch(latestPayload)) {
          completedEvidenceSupplement = true;
          latestPayload = await runAutoStep("evidence", "extract-evidence");
        }
      }
      for (const step of AUTO_DRAFT_STEPS.slice(startIndex)) {
        if (autoDraftPauseRequestedRef.current) {
          break;
        }
        latestPayload = await runAutoStep(step.stage, step.suffix);
        if (autoDraftPauseRequestedRef.current) {
          break;
        }
        const requests = latestMissingEvidenceRequests(latestPayload);
        if (step.stage === "evidence" && requests.length && !completedEvidenceSupplement) {
          completedEvidenceSupplement = true;
          latestPayload = await runAutoStep("deep", "run-deep-search", { evidenceRequests: requests });
          if (autoDraftPauseRequestedRef.current) {
            break;
          }
          latestPayload = await runAutoStep("evidence", "extract-evidence");
        }
      }
      return latestPayload;
    },
    onSettled: () => {
      setRunningStage("");
    },
  });

  const runWorkflow = () => {
    if (!activeSessionId) {
      return;
    }
    if (nextFlowNode) {
      runFlowNode(nextFlowNode);
    }
  };

  const runFlowNode = (node: ResearchFlowNode) => {
    if (!activeSessionId) {
      return;
    }
    const stage = flowNodeStage(node);
    setActiveFlowNodeId(node.id);
    setActiveStage(stage);
    setRunningFlowNodeId(node.id);
    setRunningStage(stage);
    void queryClient.invalidateQueries({ queryKey: queryKeys.researchFlowCanvas() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySession(activeSessionId) });
    flowExecuteMutation.mutate({ nodeId: node.id });
  };

  const runAction = (suffix: string, stage?: ResearchStageKey, body?: unknown) => {
    if (!activeSessionId) {
      return;
    }
    if (stage) {
      setActiveStage(stage);
    }
    setRunningStage(stage ?? "draft");
    void queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySession(activeSessionId) });
    actionMutation.mutate({
      endpoint: `/api/research/theme-discovery/sessions/${encodeURIComponent(activeSessionId)}/${suffix}`,
      body,
    });
  };

  const runEvidenceSupplementSearch = () => {
    const requests = latestMissingEvidenceRequests(active);
    if (!requests.length) {
      return;
    }
    runAction("run-deep-search", "deep", { evidenceRequests: requests });
  };

  const pauseAutoDraft = () => {
    autoDraftPauseRequestedRef.current = true;
    setAutoDraftPauseRequested(true);
  };

  const runThemeAction = (theme: ResearchCandidateTheme, suffix: string, stage?: ResearchStageKey) => {
    if (stage) {
      setActiveStage(stage);
    }
    setRunningStage(stage ?? activeStage);
    void queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySession(theme.sessionId) });
    actionMutation.mutate({
      endpoint: `/api/research/theme-discovery/sessions/${encodeURIComponent(theme.sessionId)}/themes/${encodeURIComponent(
        theme.themeId,
      )}/${suffix}`,
    });
  };

  const approveCard = (card: ResearchThemeCard) => {
    actionMutation.mutate({
      endpoint: `/api/research/theme-discovery/sessions/${encodeURIComponent(card.sessionId)}/theme-cards/${encodeURIComponent(
        card.cardId,
      )}/approve`,
    });
  };

  const deleteSession = (sessionId: string) => {
    if (deleteSessionMutation.isPending || !window.confirm(copy.deleteSessionConfirm)) {
      return;
    }
    deleteSessionMutation.mutate(sessionId);
  };

  const busy =
    createMutation.isPending ||
    deleteSessionMutation.isPending ||
    actionMutation.isPending ||
    autoDraftMutation.isPending ||
    flowExecuteMutation.isPending;
  const actionError =
    createMutation.error ||
    deleteSessionMutation.error ||
    actionMutation.error ||
    autoDraftMutation.error ||
    flowExecuteMutation.error ||
    sessionQuery.error ||
    sessionsQuery.error ||
    flowCanvasQuery.error;
  const activeStageMeta = STAGES.find((stage) => stage.id === effectiveStage) ?? STAGES[0];
  const activeStageLabel = activeFlowItem?.node.label || stageLabel(activeStageMeta.id, copy);
  const activeStageStatus = activeFlowItem
    ? displayedFlowNodeStatus(activeFlowItem.node, runningFlowNodeId)
    : displayedStageStatus(effectiveStage, active, runningStage);
  const showFallbackWorkflowModeControl = !flowStageItems.length;
  const workflowControlsDisabled = busy || !activeSessionId || !nextFlowNode;

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div className={styles.heroCopy}>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{t("researchPageTitle")}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <div className={styles.headerActions}>
          <nav className={styles.subnav} aria-label={copy.researchView}>
            <span className={`${styles.subnavLink} ${styles.subnavLinkActive}`}>
              {copy.researchView}
            </span>
            <Link className={styles.subnavLink} to="/agents/prompts?category=research">
              {copy.promptCenter}
            </Link>
            <Link className={styles.subnavLink} to="/research/flow-canvas">
              流程画布
            </Link>
          </nav>
          {showFallbackWorkflowModeControl ? (
            <div className={styles.workflowModeControl} aria-label={copy.workflowMode}>
              <span>{copy.workflowMode}</span>
              <button
                type="button"
                className={workflowMode === "manual" ? styles.workflowModeButton_active : styles.workflowModeButton}
                onClick={() => setWorkflowMode("manual")}
                aria-pressed={workflowMode === "manual"}
              >
                {copy.manualMode}
              </button>
              <button
                type="button"
                className={workflowMode === "auto" ? styles.workflowModeButton_active : styles.workflowModeButton}
                onClick={() => setWorkflowMode("auto")}
                aria-pressed={workflowMode === "auto"}
              >
                {copy.autoMode}
              </button>
            </div>
          ) : null}
          {autoDraftMutation.isPending ? (
            <button className={styles.secondaryButton} disabled={autoDraftPauseRequested} onClick={pauseAutoDraft}>
              <Pause size={16} />
              {autoDraftPauseRequested ? copy.pausing : copy.pause}
            </button>
          ) : (
            <button className={styles.primaryButton} disabled={workflowControlsDisabled} onClick={runWorkflow}>
              <Sparkles size={16} />
              {copy.continueWorkflow}
            </button>
          )}
        </div>
      </header>

      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.searchRuns}</span>
          <strong>{active?.summary.searchRunCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.sourceCount}</span>
          <strong>{active?.summary.sourceCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.evidenceCount}</span>
          <strong>{active?.summary.evidenceCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.themeCount}</span>
          <strong>{active?.summary.candidateThemeCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.staleCount}</span>
          <strong>{active?.summary.staleThemeCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.cardCount}</span>
          <strong>{active?.summary.themeCardCount ?? 0}</strong>
        </section>
      </div>

      <main className={styles.workspace}>
            <aside className={styles.sessionRail}>
          <section className={styles.intakePanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.intake}</p>
                <h2>{copy.create}</h2>
              </div>
              <FileSearch size={18} />
            </div>
            <div className={styles.intakeFields}>
              <label className={`${styles.intakeField} ${styles.intakeField_primary}`}>
                <span>{copy.openGoal}</span>
                <textarea value={draft.openGoal} onChange={(event) => setDraft({ ...draft, openGoal: event.target.value })} />
              </label>
              <label className={`${styles.intakeField} ${styles.intakeField_tall}`}>
                <span>{copy.constraints}</span>
                <textarea
                  value={draft.constraints}
                  onChange={(event) => setDraft({ ...draft, constraints: event.target.value })}
                />
              </label>
              <label className={`${styles.intakeField} ${styles.intakeField_medium}`}>
                <span>{copy.preferences}</span>
                <textarea
                  value={draft.preferences}
                  onChange={(event) => setDraft({ ...draft, preferences: event.target.value })}
                />
              </label>
            </div>
            <button className={styles.primaryButton} disabled={busy} onClick={() => createMutation.mutate()}>
              <Layers3 size={16} />
              {copy.create}
            </button>
            {actionError ? <p className={styles.errorText}>{errorMessage(actionError)}</p> : null}
          </section>

          <section className={styles.historyPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.history}</p>
                <h2>{sessions.length}</h2>
              </div>
              <Database size={18} />
            </div>
            <div className={styles.sessionList}>
              {sessions.length === 0 ? <p className={styles.emptyText}>{copy.noSession}</p> : null}
              {sessions.map((session) => (
                <div
                  key={session.sessionId}
                  className={`${styles.sessionRow} ${session.sessionId === activeSessionId ? styles.sessionRow_active : ""}`}
                >
                  <button className={styles.sessionButton} onClick={() => setActiveSessionId(session.sessionId)}>
                    <strong>{clip(session.openGoal, 72)}</strong>
                    <span>{formatDate(session.updatedAt)}</span>
                    <code>
                      {session.summary.candidateThemeCount} {copy.themeCount} / {session.status}
                    </code>
                  </button>
                  <button
                    type="button"
                    className={styles.sessionDeleteButton}
                    disabled={deleteSessionMutation.isPending}
                    title={copy.deleteSession}
                    aria-label={`${copy.deleteSession}: ${clip(session.openGoal, 36)}`}
                    onClick={() => deleteSession(session.sessionId)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          </section>
        </aside>

        <section className={styles.pipelinePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>Theme Discovery MVP</p>
              <h2>{activeStageLabel}</h2>
            </div>
            <span className={styles.countPill}>{flowStatusLabel(activeStageStatus, copy)}</span>
          </div>

          <ResearchStageOutput
            active={active}
            busy={busy}
            copy={copy}
            currentThemes={currentThemes}
            lang={lang}
            onGenerateCard={(theme) => runThemeAction(theme, "theme-card", "card")}
            onSupplementEvidence={runEvidenceSupplementSearch}
            onSelectTheme={(theme) => runThemeAction(theme, "select", "themes")}
            missingEvidenceRequests={missingEvidenceRequests}
            selectedCard={selectedCard}
            selectedTheme={selectedTheme}
            stage={effectiveStage}
            runningStage={runningStage}
          />
        </section>

            <aside className={styles.sideColumn}>
              <section className={styles.processPanel}>
            <div className={styles.stageRail}>
              {(flowStageItems.length ? flowStageItems : defaultFlowStageItems(copy)).map((item, index) => {
                const stage = item.stage;
                const StageIcon = flowStageIcon(stage, item.node.type);
                const label = item.node.label || stageLabel(stage, copy);
                const status = displayedFlowNodeStatus(item.node, runningFlowNodeId);
                const actionLabel = stageActionLabel(status, stage, copy);
                const ActionIcon = status === "done" || status === "failed" ? RefreshCw : Play;
                const isActiveStage = activeFlowItem?.node.id === item.node.id;
                const canRun = Boolean(activeSessionId && item.node.id && !flowExecuteMutation.isPending && flowNodeCanExecute(status));
                return (
                  <article
                    key={item.node.id}
                    className={`${styles.stageCard} ${isActiveStage ? styles.stageCard_active : styles.stageCard_compact}`}
                  >
                    <button
                      type="button"
                      className={styles.stageSelectButton}
                      aria-pressed={isActiveStage}
                      onClick={() => {
                        setActiveFlowNodeId(item.node.id);
                        setActiveStage(stage);
                      }}
                    >
                      <div className={styles.stageIndex}>
                        <StageIcon size={16} />
                        <span>{String(index + 1).padStart(2, "0")}</span>
                      </div>
                      <div className={styles.stageHeader}>
                        <div>
                          <strong>{label}</strong>
                          <small>{item.node.description || item.node.routeCondition || stageDescription(stage, lang)}</small>
                        </div>
                        <span>{flowStatusLabel(status, copy)}</span>
                      </div>
                    </button>
                    {isActiveStage ? <div className={styles.stageBody}>
                      <button
                        className={styles.secondaryButton}
                        disabled={busy || !canRun}
                        onClick={() => runFlowNode(item.node)}
                      >
                        <ActionIcon size={14} />
                        <span>{actionLabel}</span>
                      </button>
                    </div> : null}
                  </article>
                );
              })}
            </div>
              </section>
            </aside>
      </main>
    </section>
  );
}

function latestThemeCard(cards: ResearchThemeCard[], themeId?: string): ResearchThemeCard | undefined {
  return [...cards]
    .filter((card) => !themeId || card.themeId === themeId)
    .sort((left, right) => right.version - left.version)[0];
}

function latestSearchRun(runs: ResearchDiscoverySessionPayload["searchRuns"], phase: "broad" | "deep") {
  return [...runs].reverse().find((run) => run.phase === phase);
}

function defaultFlowStageItems(copy: (typeof COPY)["zh"]): FlowStageItem[] {
  return STAGES.map((stage, index) => ({
    stage: stage.id,
    node: {
      id: stage.id,
      label: stageLabel(stage.id, copy),
      type: stage.id === "card" ? "artifact" : "agent",
      status: "ready",
      x: 0,
      y: index * 120,
      agentKey: stage.id,
      promptKey: stage.id,
      description: "",
      routeCondition: "",
    },
  }));
}

function flowNodeStage(node: Partial<ResearchFlowNode> | undefined): ResearchStageKey {
  const key = `${node?.id ?? ""} ${node?.agentKey ?? ""} ${node?.promptKey ?? ""}`.toLowerCase();
  if (key.includes("theme_card") || key.includes(" card") || key.endsWith("card")) {
    return "card";
  }
  if (key.includes("broad")) {
    return "broad";
  }
  if (key.includes("deep")) {
    return "deep";
  }
  if (key.includes("review") || key.includes("evidence")) {
    return "evidence";
  }
  if (key.includes("theme") || key.includes("human_choice")) {
    return "themes";
  }
  if (node?.type === "artifact") {
    return "card";
  }
  if (node?.type === "decision" || node?.type === "evaluation") {
    return "evidence";
  }
  if (node?.type === "human") {
    return "themes";
  }
  return "broad";
}

function flowStageIcon(stage: ResearchStageKey, nodeType: string) {
  if (stage === "broad") return SearchCheck;
  if (stage === "deep") return Target;
  if (stage === "evidence") return BookOpenCheck;
  if (stage === "card") return BadgeCheck;
  if (nodeType === "human") return GitBranch;
  return BrainCircuit;
}

function nextRunnableFlowNode(nodes: ResearchFlowNode[]): ResearchFlowNode | undefined {
  return nodes.find((node) => ["ready", "needs_review", "needs_evidence"].includes(String(node.status || "")));
}

function flowNodeCanExecute(status: string) {
  return ["ready", "needs_review", "needs_evidence", "needs_input", "done", "failed", "stale"].includes(status);
}

function displayedFlowNodeStatus(node: ResearchFlowNode, runningNodeId: string) {
  if (runningNodeId === node.id) {
    return "running";
  }
  return node.status || "idle";
}

function autoDraftStartIndex(active: ResearchDiscoverySessionPayload | undefined) {
  if (!active) {
    return 0;
  }
  const firstIncomplete = AUTO_DRAFT_STEPS.findIndex((step) => stageStatus(step.stage, active) !== "done");
  return firstIncomplete >= 0 ? firstIncomplete : 0;
}

function autoDraftStepIndex(stage: ResearchStageKey) {
  const index = AUTO_DRAFT_STEPS.findIndex((step) => step.stage === stage);
  return index >= 0 ? index : AUTO_DRAFT_STEPS.length;
}

function nextManualWorkflowStep(active: ResearchDiscoverySessionPayload | undefined): {
  stage: ResearchStageKey;
  suffix: string;
  body?: unknown;
} | null {
  if (!active || stageStatus("broad", active) !== "done") {
    return { stage: "broad", suffix: "run-broad-search" };
  }
  if (stageStatus("deep", active) !== "done") {
    return { stage: "deep", suffix: "run-deep-search" };
  }
  if (stageStatus("evidence", active) !== "done") {
    return { stage: "evidence", suffix: "extract-evidence" };
  }
  const requests = latestMissingEvidenceRequests(active);
  if (requests.length && !hasDeepSearchAfterLatestEvidence(active)) {
    return { stage: "deep", suffix: "run-deep-search", body: { evidenceRequests: requests } };
  }
  if (requests.length && hasDeepSearchAfterLatestEvidence(active) && latestEvidenceIsOlderThanDeepSearch(active)) {
    return { stage: "evidence", suffix: "extract-evidence" };
  }
  if (stageStatus("themes", active) !== "done") {
    return { stage: "themes", suffix: "generate-themes" };
  }
  return null;
}

function latestMissingEvidenceRequests(active: ResearchDiscoverySessionPayload | undefined) {
  if (!active) {
    return [];
  }
  const event = latestResearchEvent(active, "evidence.");
  const fields = asRecord(event?.fields);
  const profile = asRecord(fields.agentExecution);
  return stringList(fields.missingEvidenceRequests).concat(stringList(profile.missingEvidenceRequests)).filter(uniqueString);
}

function latestResearchEvent(active: ResearchDiscoverySessionPayload, prefix: string) {
  return [...active.events].reverse().find((event) => event.eventCode.startsWith(prefix));
}

function hasDeepSearchAfterLatestEvidence(active: ResearchDiscoverySessionPayload) {
  const evidenceTime = timestampMs(latestResearchEvent(active, "evidence.")?.timestamp);
  return active.searchRuns.some((run) => run.phase === "deep" && timestampMs(run.completedAt || run.startedAt) > evidenceTime);
}

function latestEvidenceIsOlderThanDeepSearch(active: ResearchDiscoverySessionPayload) {
  const evidenceTime = timestampMs(latestResearchEvent(active, "evidence.")?.timestamp);
  const latestDeepTime = Math.max(
    0,
    ...active.searchRuns
      .filter((run) => run.phase === "deep")
      .map((run) => timestampMs(run.completedAt || run.startedAt)),
  );
  return latestDeepTime > evidenceTime;
}

function stageLabel(stage: ResearchStageKey, copy: (typeof COPY)["zh"]) {
  if (stage === "broad") return copy.broad;
  if (stage === "deep") return copy.deep;
  if (stage === "evidence") return copy.evidence;
  if (stage === "themes") return copy.themes;
  return copy.themeCard;
}

function ResearchStageOutput({
  active,
  busy,
  copy,
  currentThemes,
  lang,
  missingEvidenceRequests,
  onGenerateCard,
  onSupplementEvidence,
  onSelectTheme,
  selectedCard,
  selectedTheme,
  stage,
  runningStage,
}: {
  active: ResearchDiscoverySessionPayload | undefined;
  busy: boolean;
  copy: (typeof COPY)["zh"];
  currentThemes: ResearchCandidateTheme[];
  lang: "zh" | "en";
  missingEvidenceRequests: string[];
  onGenerateCard: (theme: ResearchCandidateTheme) => void;
  onSupplementEvidence: () => void;
  onSelectTheme: (theme: ResearchCandidateTheme) => void;
  selectedCard: ResearchThemeCard | undefined;
  selectedTheme: ResearchCandidateTheme | undefined;
  stage: ResearchStageKey;
  runningStage: ResearchStageKey | "draft" | "";
}) {
  const result = stageResultView(stage, active, currentThemes, selectedTheme, selectedCard, lang);
  const StageIcon = (STAGES.find((item) => item.id === stage) ?? STAGES[0]).icon;

  if (!active) {
    return <p className={styles.emptyText}>{copy.noSession}</p>;
  }

  return (
    <div className={styles.stageOutput}>
      {result ? (
        <section className={styles.stageResult}>
          <div className={styles.stageOutputHeader}>
            <span>
              <StageIcon size={17} />
            </span>
            <p className={styles.stageResultSummary}>{result.summary}</p>
          </div>
          {result.items.length ? (
            <div className={styles.stageResultItems}>
              {result.items.map((item) => (
                <div key={item.label} className={styles.stageResultItem}>
                  <strong>{item.label}</strong>
                  <em>{item.value}</em>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {stage === "broad" || stage === "deep" ? (
        <StageSources active={active} lang={lang} phase={stage} />
      ) : stage === "evidence" ? (
        <StageEvidence
          active={active}
          busy={busy}
          copy={copy}
          missingEvidenceRequests={missingEvidenceRequests}
          onSupplementEvidence={onSupplementEvidence}
        />
      ) : stage === "themes" ? (
        <StageThemes
          busy={busy}
          copy={copy}
          currentThemes={currentThemes}
          onGenerateCard={onGenerateCard}
          onSelectTheme={onSelectTheme}
        />
      ) : (
        <StageCard
          busy={busy}
          copy={copy}
          currentThemes={currentThemes}
          onGenerateCard={onGenerateCard}
          onSelectTheme={onSelectTheme}
          selectedCard={selectedCard}
          selectedTheme={selectedTheme}
        />
      )}

      <AgentTracePanel
        active={active}
        copy={copy}
        defaultCollapsed
        isRunning={runningStage === stage || runningStage === "draft"}
        stage={stage}
      />
    </div>
  );
}

function StageSources({
  active,
  lang,
  phase,
}: {
  active: ResearchDiscoverySessionPayload;
  lang: "zh" | "en";
  phase: "broad" | "deep";
}) {
  const [showAllSources, setShowAllSources] = useState(false);
  const run = latestSearchRun(active.searchRuns, phase);
  const sources =
    phase === "broad"
      ? active.sources
      : active.sources.filter((source) => !run?.runId || source.searchRunId === run.runId);
  const visibleSources = showAllSources ? sources : sources.slice(0, 12);
  const hiddenSourceCount = Math.max(0, sources.length - visibleSources.length);
  return (
    <div className={styles.evidenceList}>
      {!visibleSources.length ? <p className={styles.emptyText}>{phase === "broad" ? "还没有广撒网来源。" : "还没有定向深搜来源。"}</p> : null}
      {visibleSources.map((source) => (
        <article key={source.sourceId} className={styles.evidenceCard}>
          <a href={source.url} target="_blank" rel="noreferrer">
            <strong>{source.title}</strong>
            <span>{clip(source.snippet, 180)}</span>
          </a>
          <small>
            {sourceKindLabel(source.kind, lang)} · {source.reliability}
          </small>
        </article>
      ))}
      {sources.length > 12 ? (
        <button
          type="button"
          className={`${styles.secondaryButton} ${styles.sourceToggleButton}`}
          onClick={() => setShowAllSources((current) => !current)}
        >
          {showAllSources
            ? lang === "zh"
              ? "收起来源"
              : "Collapse sources"
            : lang === "zh"
              ? `显示全部 ${sources.length} 条来源（还有 ${hiddenSourceCount} 条）`
              : `Show all ${sources.length} sources (${hiddenSourceCount} more)`}
        </button>
      ) : null}
    </div>
  );
}

function AgentTracePanel({
  active,
  copy,
  defaultCollapsed,
  isRunning,
  stage,
}: {
  active: ResearchDiscoverySessionPayload;
  copy: (typeof COPY)["zh"];
  defaultCollapsed: boolean;
  isRunning: boolean;
  stage: ResearchStageKey;
}) {
  const trace = stageTrace(active, stage);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const initializedTraceRef = useRef("");
  const atBottomRef = useRef(true);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed && !isRunning);
  const [detailsExpanded, setDetailsExpanded] = useState(false);
  const traceSessionKey = `${active.session.sessionId}:${stage}`;
  const traceScrollSignal = useMemo(() => buildResearchTraceScrollSignal(trace, isRunning), [trace, isRunning]);
  const mainEntries = useMemo(() => trace.filter((item) => isMainTraceEntry(String(item.kind || "agent"))), [trace]);
  const detailEntries = useMemo(() => trace.filter((item) => !isMainTraceEntry(String(item.kind || "agent"))), [trace]);
  const latestTimestamp = useMemo(() => latestTraceTimestamp(trace), [trace]);

  useLayoutEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (initializedTraceRef.current !== traceSessionKey) {
      initializedTraceRef.current = traceSessionKey;
      timeline.scrollTop = timeline.scrollHeight;
      atBottomRef.current = true;
      setIsAtBottom(true);
      return;
    }
    if (atBottomRef.current) {
      timeline.scrollTop = timeline.scrollHeight;
      setIsAtBottom(true);
    }
  }, [traceSessionKey, traceScrollSignal]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    const handleScroll = () => {
      const distance = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight;
      const nextAtBottom = distance < 18;
      atBottomRef.current = nextAtBottom;
      setIsAtBottom(nextAtBottom);
    };
    handleScroll();
    timeline.addEventListener("scroll", handleScroll);
    return () => timeline.removeEventListener("scroll", handleScroll);
  }, [traceSessionKey]);

  useEffect(() => {
    setIsCollapsed(defaultCollapsed && !isRunning);
    setDetailsExpanded(false);
  }, [defaultCollapsed, isRunning, traceSessionKey]);

  const scrollToLatest = () => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    timeline.scrollTo({ top: timeline.scrollHeight, behavior: "smooth" });
    atBottomRef.current = true;
    setIsAtBottom(true);
  };

  if (!trace.length) {
    return (
      <section className={`${styles.agentTracePanel} ${isCollapsed ? styles.agentTracePanel_collapsed : ""}`}>
        <div className={styles.agentTraceHeader}>
          <div>
            <strong>Agent 执行时间线</strong>
            <span>{isRunning ? "等待第一条过程记录" : "还没有执行过程记录"}</span>
          </div>
          <div className={styles.agentTraceControls}>
            <button
              type="button"
              className={styles.traceGhostButton}
              onClick={() => setIsCollapsed((current) => !current)}
              aria-expanded={!isCollapsed}
            >
              {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
              <span>{isCollapsed ? copy.expandTrace : copy.collapseTrace}</span>
            </button>
            {isRunning ? <LoaderCircle className={styles.statusSpinner} size={15} /> : null}
          </div>
        </div>
        {!isCollapsed ? (
          <div className={styles.agentTraceTimeline}>
            <article className={`${styles.agentTraceTurn} ${styles.agentTrace_context}`}>
              <div className={styles.agentTraceAvatar}>{isRunning ? <LoaderCircle size={15} /> : <BrainCircuit size={15} />}</div>
              <div className={styles.agentTraceContent}>
                <div className={styles.agentTraceMeta}>
                  <strong>{isRunning ? "正在等待 agent 写入第一条过程记录" : "运行后这里会显示 agent 过程"}</strong>
                </div>
                <p>{isRunning ? "后端开始调用后，这里会实时显示主回答和可折叠工具过程。" : "运行或重跑当前步骤后，这里会保留可追溯过程。"}</p>
              </div>
            </article>
          </div>
        ) : null}
      </section>
    );
  }
  return (
    <section className={`${styles.agentTracePanel} ${isCollapsed ? styles.agentTracePanel_collapsed : ""}`}>
      <div className={styles.agentTraceHeader}>
        <div>
          <strong>Agent 执行时间线</strong>
          <span>
            {isRunning ? "实时跟随最新状态" : "阶段过程已记录"}
            {latestTimestamp ? ` · ${formatTraceTimestamp(latestTimestamp)}` : ""}
          </span>
        </div>
        <div className={styles.agentTraceControls}>
          <button
            type="button"
            className={styles.traceGhostButton}
            onClick={() => setIsCollapsed((current) => !current)}
            aria-expanded={!isCollapsed}
          >
            {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
            <span>{isCollapsed ? copy.expandTrace : copy.collapseTrace}</span>
          </button>
          <button
            type="button"
            className={styles.traceGhostButton}
            disabled={!detailEntries.length}
            onClick={() => setDetailsExpanded((current) => !current)}
            aria-expanded={detailsExpanded}
          >
            {detailsExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span>{detailsExpanded ? "收起细节" : `展开细节 ${detailEntries.length}`}</span>
          </button>
          {isRunning ? (
            <span className={styles.agentTraceLivePill}>
              <LoaderCircle className={styles.statusSpinner} size={13} />
              运行中
            </span>
          ) : null}
        </div>
      </div>

      {!isCollapsed ? <div ref={timelineRef} className={styles.agentTraceTimeline}>
        {isRunning ? (
          <article className={`${styles.agentTraceTurn} ${styles.agentTrace_agent}`}>
            <div className={styles.agentTraceAvatar}>
              <LoaderCircle size={15} />
            </div>
            <div className={styles.agentTraceContent}>
              <div className={styles.agentTraceMeta}>
                <strong>Agent 正在执行当前步骤</strong>
                <time>最新状态</time>
              </div>
              <p>页面会持续刷新这个过程，新的主回答、工具调用和观察结果会继续追加。</p>
            </div>
          </article>
        ) : null}

        {mainEntries.map((item, index) => (
          <ResearchTraceTurn key={traceEntryKey(item, index)} item={item} index={index} />
        ))}

        {detailEntries.length ? (
          <section className={styles.agentTraceDetailGroup}>
            <button
              type="button"
              className={styles.agentTraceDetailSummary}
              aria-expanded={detailsExpanded}
              onClick={() => setDetailsExpanded((current) => !current)}
            >
              <Wrench size={15} />
              <span>工具调用与上下文过程</span>
              <em>{detailEntries.length}</em>
              {detailsExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            </button>
            {detailsExpanded ? (
              <div className={styles.agentTraceDetailList}>
                {detailEntries.map((item, index) => (
                  <ResearchTraceDetail key={traceEntryKey(item, index)} item={item} />
                ))}
              </div>
            ) : null}
          </section>
        ) : null}

        {!mainEntries.length && !detailsExpanded ? (
          <article className={`${styles.agentTraceTurn} ${styles.agentTrace_context}`}>
            <div className={styles.agentTraceAvatar}>
              <BrainCircuit size={15} />
            </div>
            <div className={styles.agentTraceContent}>
              <div className={styles.agentTraceMeta}>
                <strong>当前只有工具与上下文过程</strong>
              </div>
              <p>展开细节可以查看提示词、输入、工具调用和观察结果。</p>
            </div>
          </article>
        ) : null}
      </div> : null}

      {!isCollapsed && !isAtBottom ? (
        <button type="button" className={styles.traceBackToBottomButton} onClick={scrollToLatest}>
          <ArrowDown size={14} />
          <span>回到最新</span>
        </button>
      ) : null}
    </section>
  );
}

function ResearchTraceTurn({ item, index }: { item: Record<string, unknown>; index: number }) {
  const kind = String(item.kind || "agent");
  return (
    <article className={`${styles.agentTraceTurn} ${styles[`agentTrace_${traceTone(kind)}`]}`}>
      <div className={styles.agentTraceAvatar}>{traceIcon(kind)}</div>
      <div className={styles.agentTraceContent}>
        <div className={styles.agentTraceMeta}>
          <strong>{String(item.title || `Agent step ${index + 1}`)}</strong>
          {item.timestamp ? <time>{formatTraceTimestamp(String(item.timestamp))}</time> : null}
        </div>
        {item.detail ? <p>{String(item.detail)}</p> : null}
      </div>
    </article>
  );
}

function ResearchTraceDetail({ item }: { item: Record<string, unknown> }) {
  const kind = String(item.kind || "agent");
  return (
    <article className={`${styles.agentTraceDetailItem} ${styles[`agentTrace_${traceTone(kind)}`]}`}>
      <span className={styles.agentTraceDetailIcon}>{traceIcon(kind)}</span>
      <div>
        <div className={styles.agentTraceMeta}>
          <strong>{String(item.title || traceLabel(kind))}</strong>
          {item.timestamp ? <time>{formatTraceTimestamp(String(item.timestamp))}</time> : null}
        </div>
        {item.detail ? <p>{String(item.detail)}</p> : null}
      </div>
    </article>
  );
}

function traceIcon(kind: string) {
  if (kind === "error") return <TriangleAlert size={15} />;
  if (kind === "tool") return <Wrench size={15} />;
  if (kind === "observation") return <SearchCheck size={15} />;
  if (kind === "prompt" || kind === "input") return <FileSearch size={15} />;
  if (kind === "plan") return <GitBranch size={15} />;
  return <Sparkles size={15} />;
}

function isMainTraceEntry(kind: string) {
  return kind === "agent" || kind === "error";
}

function buildResearchTraceScrollSignal(trace: Array<Record<string, unknown>>, isRunning: boolean) {
  return trace
    .map((item, index) =>
      [
        index,
        item.kind ?? "",
        item.title ?? "",
        String(item.detail ?? "").length,
        item.timestamp ?? "",
      ].join(":"),
    )
    .concat(isRunning ? ["running"] : ["idle"])
    .join("|");
}

function latestTraceTimestamp(trace: Array<Record<string, unknown>>) {
  return [...trace].reverse().find((item) => item.timestamp)?.timestamp?.toString() ?? "";
}

function traceEntryKey(item: Record<string, unknown>, index: number) {
  return `${String(item.timestamp || "")}-${String(item.kind || "agent")}-${String(item.title || "")}-${index}`;
}

function formatTraceTimestamp(timestamp: string) {
  if (!timestamp) {
    return "";
  }
  const value = new Date(timestamp);
  if (Number.isNaN(value.getTime())) {
    return timestamp;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(value);
}

function StageEvidence({
  active,
  busy,
  copy,
  missingEvidenceRequests,
  onSupplementEvidence,
}: {
  active: ResearchDiscoverySessionPayload;
  busy: boolean;
  copy: (typeof COPY)["zh"];
  missingEvidenceRequests: string[];
  onSupplementEvidence: () => void;
}) {
  const visibleEvidence = active.evidence.slice(0, 12);
  return (
    <div className={styles.evidenceList}>
      {missingEvidenceRequests.length ? (
        <section className={styles.evidenceRequestPanel}>
          <div>
            <strong>{copy.evidenceRequests}</strong>
            <span>{missingEvidenceRequests.length}</span>
          </div>
          <ul>
            {missingEvidenceRequests.slice(0, 5).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <button className={styles.secondaryButton} disabled={busy} onClick={onSupplementEvidence}>
            <SearchCheck size={14} />
            {copy.confirmEvidenceSearch}
          </button>
        </section>
      ) : null}
      {!visibleEvidence.length ? <p className={styles.emptyText}>还没有证据记录。</p> : null}
      {visibleEvidence.map((item) => (
        <article key={item.evidenceId} className={styles.evidenceCard}>
          <strong>{item.claim}</strong>
          <span>
            {item.evidenceType} · {item.confidence}
          </span>
          <small>{item.note}</small>
        </article>
      ))}
    </div>
  );
}

function StageThemes({
  busy,
  copy,
  currentThemes,
  onGenerateCard,
  onSelectTheme,
}: {
  busy: boolean;
  copy: (typeof COPY)["zh"];
  currentThemes: ResearchCandidateTheme[];
  onGenerateCard: (theme: ResearchCandidateTheme) => void;
  onSelectTheme: (theme: ResearchCandidateTheme) => void;
}) {
  return (
    <div className={styles.themeGrid}>
      {currentThemes.length === 0 ? <p className={styles.emptyText}>{copy.emptyCandidates}</p> : null}
      {currentThemes.map((theme, index) => (
        <ThemeCompareRow
          key={theme.themeId}
          busy={busy}
          copy={copy}
          index={index}
          onGenerateCard={onGenerateCard}
          onSelectTheme={onSelectTheme}
          theme={theme}
        />
      ))}
    </div>
  );
}

function ThemeCompareRow({
  busy,
  cardPrimary = false,
  copy,
  index,
  isSelected = false,
  onGenerateCard,
  onSelectTheme,
  theme,
}: {
  busy: boolean;
  cardPrimary?: boolean;
  copy: (typeof COPY)["zh"];
  index: number;
  isSelected?: boolean;
  onGenerateCard: (theme: ResearchCandidateTheme) => void;
  onSelectTheme: (theme: ResearchCandidateTheme) => void;
  theme: ResearchCandidateTheme;
}) {
  const disabled = busy || theme.status === "stale";
  return (
    <article className={`${styles.themeCompareRow} ${isSelected ? styles.themeCompareRow_selected : ""}`}>
      <div className={styles.themeCompareRank}>
        <span>{String(index + 1).padStart(2, "0")}</span>
        <strong>{Math.round(theme.recommendationScore)}</strong>
      </div>
      <div className={styles.themeCompareMain}>
        <div className={styles.themeCompareHeader}>
          <div>
            <h3>{theme.title}</h3>
            <p>{theme.oneLine}</p>
          </div>
          <span className={`${styles.statePill} ${styles[`state_${themeTone(theme.status)}`]}`}>
            {isSelected ? copy.selected : statusLabel(theme.status, copy)}
          </span>
        </div>
        <p className={styles.themeCompareQuestion}>{theme.coreQuestion}</p>
        <div className={styles.themeCompareTags}>
          <code>{noveltyLabel(theme.noveltyPath)}</code>
          {theme.interdisciplinaryCombination.slice(0, 3).map((item) => (
            <code key={item}>{item}</code>
          ))}
        </div>
      </div>
      <div className={styles.themeCompareMetrics}>
        <Metric label={copy.novelty} value={score(theme, "noveltyGap")} />
        <Metric label={copy.competition} value={score(theme, "competitionFit")} />
        <Metric label={copy.data} value={score(theme, "verifiability")} />
      </div>
      <div className={styles.themeCompareReview}>
        <BrainCircuit size={14} />
        <span>{clip(theme.agentReview || theme.uncertainty, 92)}</span>
      </div>
      <div className={styles.themeCompareActions}>
        <button
          className={cardPrimary ? styles.secondaryButton : styles.primaryButton}
          disabled={disabled || isSelected}
          onClick={() => onSelectTheme(theme)}
        >
          <GitBranch size={14} />
          <span>{isSelected ? copy.selected : copy.select}</span>
        </button>
        <button
          className={cardPrimary ? styles.primaryButton : styles.secondaryButton}
          disabled={disabled}
          onClick={() => onGenerateCard(theme)}
        >
          <FlaskConical size={14} />
          <span>{cardPrimary ? copy.formalCard : copy.themeCard}</span>
        </button>
      </div>
    </article>
  );
}

function StageCard({
  busy,
  copy,
  currentThemes,
  onGenerateCard,
  onSelectTheme,
  selectedCard,
  selectedTheme,
}: {
  busy: boolean;
  copy: (typeof COPY)["zh"];
  currentThemes: ResearchCandidateTheme[];
  onGenerateCard: (theme: ResearchCandidateTheme) => void;
  onSelectTheme: (theme: ResearchCandidateTheme) => void;
  selectedCard: ResearchThemeCard | undefined;
  selectedTheme: ResearchCandidateTheme | undefined;
}) {
  const previewThemes = currentThemes.filter((theme) => theme.status !== "stale");
  const visibleThemes = previewThemes.length ? previewThemes : currentThemes;
  if (!selectedCard) {
    return (
      <div className={styles.themeGrid}>
        <section className={styles.cardPreviewIntro}>
          <div>
            <strong>{copy.candidateCardPreview}</strong>
            <span>{visibleThemes.length ? `${visibleThemes.length} ${copy.candidates}` : copy.emptyCard}</span>
          </div>
          <p>{copy.previewBeforeCard}</p>
        </section>
        {visibleThemes.length === 0 ? <p className={styles.emptyText}>{copy.emptyCandidates}</p> : null}
        {visibleThemes.map((theme, index) => {
          const isSelected = selectedTheme?.themeId === theme.themeId;
          return (
            <ThemeCompareRow
              key={theme.themeId}
              busy={busy}
              cardPrimary
              copy={copy}
              index={index}
              isSelected={isSelected}
              onGenerateCard={onGenerateCard}
              onSelectTheme={onSelectTheme}
              theme={theme}
            />
          );
        })}
      </div>
    );
  }
  return (
    <article className={styles.themeCard}>
      <div className={styles.themeRank}>
        <span>v{selectedCard.version}</span>
        <strong>{selectedCard.status === "approved" ? "OK" : "D"}</strong>
      </div>
      <div className={styles.themePlan}>
        <div className={styles.themeHeader}>
          <div>
            <h3>{selectedCard.title}</h3>
            <p>{selectedCard.oneLine}</p>
          </div>
          <span className={`${styles.statePill} ${styles[`state_${themeTone(selectedCard.status)}`]}`}>
            {statusLabel(selectedCard.status, copy)}
          </span>
        </div>
        <p className={styles.questionText}>{selectedCard.coreScientificQuestion}</p>
        <section>
          <strong>{copy.novelty}</strong>
          <p>{selectedCard.whyNovel}</p>
        </section>
        <section>
          <strong>{copy.competition}</strong>
          <p>{selectedCard.whyCompetitionFit}</p>
        </section>
        <section>
          <strong>{copy.data}</strong>
          <ul>
            {selectedCard.possibleDatasets.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
        <section>
          <strong>{copy.themes}</strong>
          <ul>
            {selectedCard.possibleMethods.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
        <section>
          <strong>{copy.risk}</strong>
          <ul>
            {selectedCard.risks.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      </div>
    </article>
  );
}

function stageResultView(
  stage: string,
  active: ResearchDiscoverySessionPayload | undefined,
  currentThemes: ResearchCandidateTheme[],
  selectedTheme: ResearchCandidateTheme | undefined,
  selectedCard: ResearchThemeCard | undefined,
  lang: "zh" | "en",
): { summary: string; items: Array<{ label: string; value: string }> } | null {
  const copy =
    lang === "zh"
      ? {
          waiting: "等待创建会话后开始调研。",
          queries: "查询",
          sources: "来源",
          failed: "失败",
          status: "状态",
          reason: "原因",
          sample: "样例",
          evidence: "证据",
          gap: "缺口",
          dataset: "数据",
          method: "方法",
          implementation: "实现",
          themes: "候选",
          top: "最强",
          path: "路径",
          theme: "主题",
          card: "卡片",
          datasets: "数据集",
          pending: "待生成",
        }
      : {
          waiting: "Create a session first to start research.",
          queries: "Queries",
          sources: "Sources",
          failed: "Fails",
          status: "Status",
          reason: "Reason",
          sample: "Sample",
          evidence: "Evidence",
          gap: "Gap",
          dataset: "Dataset",
          method: "Method",
          implementation: "Implementation",
          themes: "Candidates",
          top: "Best",
          path: "Path",
          theme: "Theme",
          card: "Card",
          datasets: "Datasets",
          pending: "Pending",
        };

  if (!active) {
    return { summary: copy.waiting, items: [] };
  }

  if (stage === "broad" || stage === "deep") {
    const run = latestSearchRun(active.searchRuns, stage);
    if (!run) {
      return {
        summary: stage === "broad" ? "等待开始广撒网调研。" : "等待开始定向深搜。",
        items: [
          { label: copy.status, value: "ready" },
          { label: copy.queries, value: "0" },
          { label: copy.sources, value: "0" },
          { label: copy.sample, value: copy.pending },
        ],
      };
    }
    const failure = runFailure(run);
    if (failure) {
      return {
        summary:
          stage === "broad"
            ? `广撒网失败：${failure.message}`
            : `定向深搜失败：${failure.message}`,
        items: [
          { label: copy.status, value: "failed" },
          { label: copy.queries, value: `${run?.queries.length ?? 0}` },
          { label: copy.reason, value: failure.type || "error" },
          { label: copy.sample, value: clip(failure.message, 54) },
        ],
      };
    }
    const execution = asRecord(asRecord(run?.modelProfile).searchExecution);
    const sourceCounts = asRecord(execution.sourceCounts);
    const totalSources = sumRecordNumbers(sourceCounts);
    const queryCount = run?.queries.length ?? 0;
    const failedCount = numberFrom(execution.failedAttemptCount);
    const sources = active.sources.filter((item) => stage === "broad" || item.searchRunId === run?.runId);
    const sampleSource = sources[0];
    const isCompleted = run.status === "completed";
    return {
      summary: isCompleted
        ? stage === "broad"
          ? `已完成广撒网：${queryCount} 组查询，收集 ${totalSources} 条来源，${failedCount} 次失败。`
          : `已完成定向深搜：${queryCount} 组查询，收集 ${totalSources} 条来源，${failedCount} 次失败。`
        : stage === "broad"
          ? `广撒网进行中：已记录 ${queryCount} 组查询，当前 ${totalSources} 条来源。`
          : `定向深搜进行中：已记录 ${queryCount} 组查询，当前 ${totalSources} 条来源。`,
      items: isCompleted
        ? [
            { label: copy.queries, value: `${queryCount}` },
            { label: copy.sources, value: `${totalSources}` },
            { label: copy.failed, value: `${failedCount}` },
            {
              label: copy.sample,
              value: sampleSource
                ? `${clip(sampleSource.title, 42)} · ${sourceKindLabel(sampleSource.kind, lang)}`
                : clip(run.queries[0] || copy.pending, 54),
            },
          ]
        : [
            { label: copy.status, value: run.status },
            { label: copy.queries, value: `${queryCount}` },
            { label: copy.sources, value: `${totalSources}` },
            { label: copy.failed, value: `${failedCount}` },
          ],
    };
  }

  if (stage === "evidence") {
    if (!active.evidence.length) {
      return {
        summary: "等待抽取证据。完成广撒网和定向深搜后，这里会显示可复核证据。",
        items: [
          { label: copy.status, value: "ready" },
          { label: copy.gap, value: "0" },
          { label: copy.dataset, value: "0" },
          { label: copy.sample, value: copy.pending },
        ],
      };
    }
    const evidenceCounts = active.evidence.reduce<Record<string, number>>((acc, item) => {
      acc[item.evidenceType] = (acc[item.evidenceType] || 0) + 1;
      return acc;
    }, {});
    return {
      summary: `已抽取 ${active.evidence.length} 条证据，并整理成可复核记录。`,
      items: [
        { label: copy.gap, value: `${evidenceCounts.gap || 0}` },
        { label: copy.dataset, value: `${evidenceCounts.dataset || 0}` },
        { label: copy.method, value: `${evidenceCounts.method || 0}` },
        { label: copy.implementation, value: `${evidenceCounts.implementation || 0}` },
        {
          label: copy.sample,
          value: active.evidence[0]
            ? clip(active.evidence[0].claim, 42)
            : copy.pending,
        },
      ],
    };
  }

  if (stage === "themes") {
    const shortlisted = currentThemes.filter((theme) => theme.status === "shortlisted" || theme.status === "selected");
    const best = shortlisted[0];
    if (!best) {
      return {
        summary: "等待生成候选主题。证据抽取完成后，这里会进入 5 个候选主题比较。",
        items: [
          { label: copy.status, value: "ready" },
          { label: copy.themes, value: "0" },
          { label: copy.top, value: copy.pending },
          { label: copy.path, value: copy.pending },
        ],
      };
    }
    return {
      summary: `已生成 ${shortlisted.length} 个候选主题，并完成去重与打分。`,
      items: [
        { label: copy.themes, value: `${shortlisted.length}` },
        { label: copy.top, value: best ? `${clip(best.title, 34)} · ${Math.round(best.recommendationScore)}` : "0" },
        { label: copy.path, value: best ? noveltyLabel(best.noveltyPath) : copy.pending },
        {
          label: copy.sample,
          value: best ? clip(best.coreQuestion, 42) : copy.pending,
        },
      ],
    };
  }

  if (stage === "card") {
    if (!selectedTheme) {
      return { summary: copy.pending, items: [] };
    }
    return {
      summary: selectedCard
        ? `已生成 ${selectedCard.status === "approved" ? "批准" : "概念级"}主题卡。`
        : "选择主题后可以生成主题卡。",
      items: [
        { label: copy.theme, value: clip(selectedTheme.title, 34) },
        { label: copy.card, value: selectedCard ? `v${selectedCard.version} · ${selectedCard.status}` : copy.pending },
        { label: copy.datasets, value: selectedCard ? `${selectedCard.possibleDatasets.length}` : "0" },
        {
          label: copy.sample,
          value: selectedCard ? clip(selectedCard.possibleMethods[0] || selectedCard.whyCompetitionFit, 42) : copy.pending,
        },
      ],
    };
  }

  return null;
}

function sourceKindLabel(kind: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    paper: "论文",
    github: "代码",
    dataset: "数据集",
    web: "网页",
  };
  const en: Record<string, string> = {
    paper: "paper",
    github: "github",
    dataset: "dataset",
    web: "web",
  };
  return (lang === "zh" ? zh : en)[kind] || kind;
}

function stageTrace(active: ResearchDiscoverySessionPayload, stage: ResearchStageKey): Array<Record<string, unknown>> {
  if (stage === "broad" || stage === "deep") {
    const run = latestSearchRun(active.searchRuns, stage);
    const trace = traceFromUnknown(asRecord(asRecord(run?.modelProfile).agentExecution).trace);
    const failure = runFailure(run);
    if (!failure) {
      return trace;
    }
    return [
      ...trace,
      {
        kind: "error",
        title: `${failure.type || "Agent"} 失败`,
        detail: failure.message,
        timestamp: run?.completedAt || "",
      },
    ];
  }
  const eventPrefix =
    stage === "evidence"
      ? "evidence."
      : stage === "themes"
        ? "themes."
        : "theme_card.";
  const event = [...active.events].reverse().find((item) => item.eventCode.startsWith(eventPrefix));
  return traceFromUnknown(event?.fields?.trace);
}

function traceFromUnknown(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
}

function traceTone(kind: string) {
  if (kind === "error") return "error";
  if (kind === "tool") return "tool";
  if (kind === "observation") return "observation";
  if (kind === "prompt" || kind === "input" || kind === "plan") return "context";
  return "agent";
}

function traceLabel(kind: string) {
  if (kind === "error") return "失败";
  if (kind === "tool") return "工具";
  if (kind === "observation") return "观察";
  if (kind === "prompt") return "提示";
  if (kind === "input") return "输入";
  if (kind === "plan") return "计划";
  return "Agent";
}

function shouldRefreshDefaultDraft(value: string, field: keyof DraftInput, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  return !normalized || normalized === PREVIOUS_DEFAULT_INPUT[lang][field];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function uniqueString(value: string, index: number, values: string[]) {
  return values.indexOf(value) === index;
}

function timestampMs(value: unknown) {
  const date = new Date(String(value || ""));
  const time = date.getTime();
  return Number.isNaN(time) ? 0 : time;
}

function sumRecordNumbers(record: Record<string, unknown>): number {
  return Object.values(record).reduce((total: number, value) => total + numberFrom(value), 0);
}

function numberFrom(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function score(theme: ResearchCandidateTheme, key: string) {
  return Number(theme.scores[key] ?? 0);
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <span>
      <strong>{typeof value === "number" ? Math.round(value) : value}</strong>
      <em>{label}</em>
    </span>
  );
}

function noveltyLabel(value: string) {
  return value.replaceAll("_", " ");
}

function themeTone(status: string) {
  if (status === "selected" || status === "approved") {
    return "ready";
  }
  if (status === "stale") {
    return "blocked";
  }
  return "draft";
}

function statusLabel(status: string, copy: (typeof COPY)["zh"]) {
  if (status === "selected") return copy.selected;
  if (status === "shortlisted") return copy.shortlisted;
  if (status === "stale") return copy.stale;
  if (status === "approved") return copy.approved;
  return copy.draft;
}

function stageStatus(stage: string, active?: ResearchDiscoverySessionPayload) {
  if (!active) {
    return "idle";
  }
  if (stage === "broad") {
    return searchRunStageStatus(active, "broad");
  }
  if (stage === "deep") {
    return searchRunStageStatus(active, "deep");
  }
  if (stage === "evidence") {
    return active.evidence.length ? "done" : "ready";
  }
  if (stage === "themes") {
    return active.summary.candidateThemeCount ? "done" : "ready";
  }
  return active.themeCards.length ? "done" : "ready";
}

function displayedStageStatus(
  stage: ResearchStageKey,
  active: ResearchDiscoverySessionPayload | undefined,
  runningStage: ResearchStageKey | "draft" | "",
) {
  if (runningStage === stage) {
    return "running";
  }
  return stageStatus(stage, active);
}

function stageStatusLabel(status: string, copy: (typeof COPY)["zh"]) {
  if (status === "done") return copy.complete;
  if (status === "running") return copy.running;
  if (status === "failed") return copy.failed;
  return copy.ready;
}

function flowStatusLabel(status: string, copy: (typeof COPY)["zh"]) {
  const english = copy.ready === "Ready";
  if (status === "done" || status === "completed") return copy.complete;
  if (status === "running") return copy.running;
  if (status === "failed") return copy.failed;
  if (status === "needs_review") return english ? "Review" : "待审查";
  if (status === "needs_input") return english ? "Input" : "待输入";
  if (status === "needs_evidence") return english ? "Evidence" : "缺证据";
  if (status === "blocked") return english ? "Blocked" : "阻塞";
  if (status === "stale") return copy.stale;
  if (status === "skipped") return english ? "Skipped" : "跳过";
  return copy.ready;
}

function stageActionLabel(status: string, stage: ResearchStageKey, copy: (typeof COPY)["zh"]) {
  if (status === "running") return copy.running;
  if (status === "done" || status === "failed") return copy.rerun;
  if (stage === "card" && status === "ready") return copy.start;
  return copy.start;
}

function searchRunStageStatus(active: ResearchDiscoverySessionPayload, phase: "broad" | "deep") {
  const latest = latestSearchRun(active.searchRuns, phase);
  if (!latest) {
    return "ready";
  }
  if (latest.status === "running") {
    return "running";
  }
  if (latest.status === "failed") {
    return "failed";
  }
  if (latest.status === "completed") {
    return "done";
  }
  return "ready";
}

function stageDescription(stage: string, lang: "zh" | "en") {
  const zh = {
    broad: "先建立领域地图，避免过早固定主题。",
    deep: "围绕高潜力交叉点继续搜索论文、代码和数据。",
    evidence: "把来源整理成带可信度的证据记录。",
    themes: "生成新颖性优先、去重后的五个候选主题。",
    card: "把选中的主题整理成概念级研究主题卡。",
  };
  const en = {
    broad: "Map the field before locking a topic too early.",
    deep: "Search papers, code, and datasets around promising intersections.",
    evidence: "Convert sources into confidence-scored evidence records.",
    themes: "Generate five novelty-first, de-duplicated candidate themes.",
    card: "Turn the selected theme into a concept-level research card.",
  };
  return (lang === "zh" ? zh : en)[stage as keyof typeof zh];
}

function clip(value: string, length: number) {
  return value.length > length ? `${value.slice(0, length - 1)}...` : value;
}

function runFailure(run: ResearchDiscoverySessionPayload["searchRuns"][number] | undefined) {
  const failure = asRecord(asRecord(run?.modelProfile).failure);
  const message = String(failure.message || "").trim();
  const type = String(failure.type || "").trim();
  if (run?.status !== "failed" && !message && !type) {
    return null;
  }
  return {
    type,
    message: message || "Research agent failed before returning a result.",
  };
}

function formatDate(value: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error || "");
}
