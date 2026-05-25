import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  BookOpenCheck,
  BrainCircuit,
  CheckCircle2,
  Database,
  FileSearch,
  FlaskConical,
  GitBranch,
  Layers3,
  RadioTower,
  RefreshCw,
  RotateCcw,
  SearchCheck,
  Sparkles,
  Target,
  Save,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ResearchCandidateTheme,
  ResearchDiscoverySessionList,
  ResearchDiscoverySessionPayload,
  ResearchPromptWorkspace,
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

type ResearchViewKey = "discovery" | "prompts";

type ResearchPromptDraft = {
  key: string;
  filename: string;
  content: string;
};

const COPY = {
  zh: {
    eyebrow: "AI Scientist Theme Discovery",
    subtitle: "从开放目标出发，联网调研并发现新颖性优先的候选科研主题。",
    create: "创建会话",
    runDraft: "一键草稿",
    broad: "广撒网",
    deep: "定向深搜",
    evidence: "抽取证据",
    themes: "生成主题",
    select: "选择",
    themeCard: "主题卡",
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
    researchView: "科研",
    promptWorkspace: "工作区提示词",
    promptBody: "工作区是真值来源。这里编辑的内容会直接写入 `workspace/prompts/research/`。",
    promptSave: "保存提示词",
    promptReset: "恢复当前内容",
    promptSaved: "已保存到工作区",
    promptLoading: "正在读取科研提示词...",
    promptEmpty: "尚未找到提示词文件，保存后会自动创建。",
    promptKeys: {
      broad: "广撒网 agent",
      deep: "定向深搜 agent",
      review: "证据审查 agent",
      themes: "主题生成 agent",
      card: "主题卡 agent",
    },
    selectedCard: "概念级主题卡",
    agentReview: "Agent 自评",
    agentReport: "Agent 调研报告",
    agentMode: "真实网络状态",
    liveNetwork: "真实联网",
    mixedLegacy: "含历史/测试数据",
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
      openGoal: "找一个计算机相关、适合 AI Scientist 赛题的新颖交叉学科研究主题。",
      constraints: "学生团队可做；能基于公开论文、GitHub、数据集或网页资料进行初步验证；适合比赛 MVP 展示。",
      preferences: "更偏新颖；优先问题视角创新，其次方法迁移、学科组合、应用场景；避免普通 RAG 或文献综述工具。",
    },
  },
  en: {
    eyebrow: "AI Scientist Theme Discovery",
    subtitle: "Start from an open goal, search public sources, and find novelty-first research themes.",
    create: "Create session",
    runDraft: "Run draft",
    broad: "Broad search",
    deep: "Deep search",
    evidence: "Extract evidence",
    themes: "Generate themes",
    select: "Select",
    themeCard: "Theme card",
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
    researchView: "Research",
    promptWorkspace: "Workspace prompts",
    promptBody: "The workspace is the source of truth. Changes here are written directly into `workspace/prompts/research/`.",
    promptSave: "Save prompts",
    promptReset: "Reset current content",
    promptSaved: "Saved to workspace",
    promptLoading: "Loading research prompts...",
    promptEmpty: "No prompt files found yet. Saving will create them.",
    promptKeys: {
      broad: "Broad-search agent",
      deep: "Deep-search agent",
      review: "Evidence-review agent",
      themes: "Theme-generation agent",
      card: "Theme-card agent",
    },
    selectedCard: "Concept theme card",
    agentReview: "Agent review",
    agentReport: "Agent research report",
    agentMode: "Live-search state",
    liveNetwork: "Live network",
    mixedLegacy: "Mixed or legacy data",
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
      openGoal: "Find a novel interdisciplinary research theme related to computer science for the AI Scientist topic.",
      constraints:
        "Suitable for a student team; grounded in public papers, GitHub, datasets, or web sources; suitable for a competition MVP.",
      preferences:
        "Novelty first; prioritize problem-perspective novelty, then method transfer, discipline combination, and application scenario; avoid generic RAG or literature-review tools.",
    },
  },
};

const STAGES = [
  { id: "broad", icon: SearchCheck },
  { id: "deep", icon: Target },
  { id: "evidence", icon: BookOpenCheck },
  { id: "themes", icon: BrainCircuit },
  { id: "card", icon: BadgeCheck },
];

const RESEARCH_PROMPT_KEYS = ["broad", "deep", "review", "themes", "card"] as const;

export function ResearchRoute() {
  const { lang, t } = useAppI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const [activeSessionId, setActiveSessionId] = useState("");
  const [activeView, setActiveView] = useState<ResearchViewKey>("discovery");
  const [draft, setDraft] = useState<DraftInput>(copy.defaultInput);
  const [promptDrafts, setPromptDrafts] = useState<Record<string, ResearchPromptDraft>>({});

  useEffect(() => {
    setDraft((current) => ({
      openGoal: current.openGoal || copy.defaultInput.openGoal,
      constraints: current.constraints || copy.defaultInput.constraints,
      preferences: current.preferences || copy.defaultInput.preferences,
    }));
  }, [copy.defaultInput.constraints, copy.defaultInput.openGoal, copy.defaultInput.preferences]);

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
  });

  const active = sessionQuery.data;
  const promptsQuery = useQuery({
    queryKey: queryKeys.researchThemeDiscoveryPrompts(),
    queryFn: () => fetchJson<ResearchPromptWorkspace>("/api/research/theme-discovery/prompts"),
    enabled: activeView === "prompts",
  });

  useEffect(() => {
    if (activeView !== "prompts" || !promptsQuery.data) {
      return;
    }
    setPromptDrafts((current) => {
      const next: Record<string, ResearchPromptDraft> = {};
      for (const item of promptsQuery.data?.prompts ?? []) {
        next[item.key] = {
          key: item.key,
          filename: item.filename,
          content: current[item.key]?.content ?? item.content ?? "",
        };
      }
      return next;
    });
  }, [activeView, promptsQuery.data]);

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

  const invalidateResearch = async (sessionId?: string) => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySessions() });
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
      await invalidateResearch(payload.session.sessionId);
    },
  });

  const actionMutation = useMutation({
    mutationFn: (endpoint: string) =>
      fetchJson<ResearchDiscoverySessionPayload>(endpoint, {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setActiveSessionId(payload.session.sessionId);
      await invalidateResearch(payload.session.sessionId);
    },
  });

  const runAction = (suffix: string) => {
    if (!activeSessionId) {
      return;
    }
    actionMutation.mutate(`/api/research/theme-discovery/sessions/${encodeURIComponent(activeSessionId)}/${suffix}`);
  };

  const runThemeAction = (theme: ResearchCandidateTheme, suffix: string) => {
    actionMutation.mutate(
      `/api/research/theme-discovery/sessions/${encodeURIComponent(theme.sessionId)}/themes/${encodeURIComponent(
        theme.themeId,
      )}/${suffix}`,
    );
  };

  const approveCard = (card: ResearchThemeCard) => {
    actionMutation.mutate(
      `/api/research/theme-discovery/sessions/${encodeURIComponent(card.sessionId)}/theme-cards/${encodeURIComponent(
        card.cardId,
      )}/approve`,
    );
  };

  const busy = createMutation.isPending || actionMutation.isPending;
  const actionError = createMutation.error || actionMutation.error || sessionQuery.error || sessionsQuery.error;
  const promptWorkspace = promptsQuery.data;
  const promptItems = useMemo(
    () => RESEARCH_PROMPT_KEYS.map((key) => promptDrafts[key]).filter(Boolean),
    [promptDrafts],
  );

  const savePromptMutation = useMutation({
    mutationFn: (payload: { key: string; content: string }) =>
      fetchJson<ResearchPromptWorkspace>("/api/research/theme-discovery/prompts", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: async (payload) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoveryPrompts() });
      setPromptDrafts(
        Object.fromEntries(
          payload.prompts.map((item) => [
            item.key,
            {
              key: item.key,
              filename: item.filename,
              content: item.content,
            },
          ]),
        ) as Record<string, ResearchPromptDraft>,
      );
    },
  });

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
            <button
              type="button"
              className={activeView === "discovery" ? `${styles.subnavLink} ${styles.subnavLinkActive}` : styles.subnavLink}
              onClick={() => setActiveView("discovery")}
            >
              {copy.researchView}
            </button>
            <button
              type="button"
              className={activeView === "prompts" ? `${styles.subnavLink} ${styles.subnavLinkActive}` : styles.subnavLink}
              onClick={() => setActiveView("prompts")}
            >
              {copy.prompts}
            </button>
          </nav>
          <button className={styles.primaryButton} disabled={busy || !activeSessionId} onClick={() => runAction("run-draft")}>
            <Sparkles size={16} />
            {copy.runDraft}
          </button>
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

      <main className={activeView === "prompts" ? styles.promptWorkspace : styles.workspace}>
        {activeView === "prompts" ? (
          <section className={styles.promptPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.promptWorkspace}</p>
                <h2>{promptWorkspace?.root ? promptWorkspace.root : copy.promptWorkspace}</h2>
              </div>
              <RadioTower size={18} />
            </div>
            <p className={styles.panelLead}>{copy.promptBody}</p>
            {promptsQuery.isPending ? <p className={styles.emptyText}>{copy.promptLoading}</p> : null}
            {!promptItems.length && !promptsQuery.isPending ? <p className={styles.emptyText}>{copy.promptEmpty}</p> : null}
            <div className={styles.promptGrid}>
              {promptItems.map((item) => (
                <article key={item.key} className={styles.promptCard}>
                  <div className={styles.promptCardHeader}>
                    <div>
                      <p className={styles.panelEyebrow}>{copy.promptKeys[item.key as keyof typeof copy.promptKeys] ?? item.key}</p>
                      <h3>{item.filename}</h3>
                    </div>
                    <span className={styles.promptPath}>{item.key}</span>
                  </div>
                  <textarea
                    className={styles.promptTextarea}
                    value={item.content}
                    onChange={(event) =>
                      setPromptDrafts((current) => ({
                        ...current,
                        [item.key]: {
                          ...item,
                          content: event.target.value,
                        },
                      }))
                    }
                  />
                  <div className={styles.cardActions}>
                    <button
                      className={styles.primaryButton}
                      disabled={savePromptMutation.isPending}
                      onClick={() =>
                        savePromptMutation.mutate({
                          key: item.key,
                          content: promptDrafts[item.key]?.content ?? "",
                        })
                      }
                    >
                      <Save size={15} />
                      {copy.promptSave}
                    </button>
                    <button
                      className={styles.secondaryButton}
                      disabled={savePromptMutation.isPending}
                      onClick={() =>
                        setPromptDrafts((current) => ({
                          ...current,
                          [item.key]: {
                            ...item,
                            content: promptsQuery.data?.prompts.find((prompt) => prompt.key === item.key)?.content ?? "",
                          },
                        }))
                      }
                    >
                      <RotateCcw size={15} />
                      {copy.promptReset}
                    </button>
                  </div>
                </article>
              ))}
            </div>
            {savePromptMutation.isSuccess ? <p className={styles.okText}>{copy.promptSaved}</p> : null}
            {savePromptMutation.error ? <p className={styles.errorText}>{errorMessage(savePromptMutation.error)}</p> : null}
          </section>
        ) : null}

        {activeView === "discovery" ? (
          <>
            <aside className={styles.sessionRail}>
          <section className={styles.intakePanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.intake}</p>
                <h2>{copy.create}</h2>
              </div>
              <FileSearch size={18} />
            </div>
            <label>
              <span>{copy.openGoal}</span>
              <textarea value={draft.openGoal} onChange={(event) => setDraft({ ...draft, openGoal: event.target.value })} />
            </label>
            <label>
              <span>{copy.constraints}</span>
              <textarea
                value={draft.constraints}
                onChange={(event) => setDraft({ ...draft, constraints: event.target.value })}
              />
            </label>
            <label>
              <span>{copy.preferences}</span>
              <textarea
                value={draft.preferences}
                onChange={(event) => setDraft({ ...draft, preferences: event.target.value })}
              />
            </label>
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
                <button
                  key={session.sessionId}
                  className={`${styles.sessionButton} ${
                    session.sessionId === activeSessionId ? styles.sessionButton_active : ""
                  }`}
                  onClick={() => setActiveSessionId(session.sessionId)}
                >
                  <strong>{clip(session.openGoal, 72)}</strong>
                  <span>{formatDate(session.updatedAt)}</span>
                  <code>
                    {session.summary.candidateThemeCount} {copy.themeCount} / {session.status}
                  </code>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className={styles.pipelinePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>Theme Discovery MVP</p>
              <h2>{copy.candidates}</h2>
            </div>
            <span className={styles.countPill}>5</span>
          </div>

          <div className={styles.themeGrid}>
            {currentThemes.length === 0 ? <p className={styles.emptyText}>{copy.emptyCandidates}</p> : null}
            {currentThemes.map((theme, index) => (
              <article key={theme.themeId} className={styles.themeCard}>
                <div className={styles.themeRank}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{Math.round(theme.recommendationScore)}</strong>
                </div>
                <div className={styles.themeBody}>
                  <div className={styles.themeHeader}>
                    <div>
                      <h3>{theme.title}</h3>
                      <p>{theme.oneLine}</p>
                    </div>
                    <span className={`${styles.statePill} ${styles[`state_${themeTone(theme.status)}`]}`}>
                      {statusLabel(theme.status, copy)}
                    </span>
                  </div>
                  <p className={styles.questionText}>{theme.coreQuestion}</p>
                  <div className={styles.scoreStrip}>
                    <Metric label={copy.score} value={theme.recommendationScore} />
                    <Metric label={copy.novelty} value={score(theme, "noveltyGap")} />
                    <Metric label={copy.competition} value={score(theme, "competitionFit")} />
                    <Metric label={copy.data} value={score(theme, "verifiability")} />
                  </div>
                  <div className={styles.tagRow}>
                    <code>{noveltyLabel(theme.noveltyPath)}</code>
                    {theme.interdisciplinaryCombination.slice(0, 4).map((item) => (
                      <code key={item}>{item}</code>
                    ))}
                  </div>
                  <div className={styles.agentReview}>
                    <BrainCircuit size={15} />
                    <p>{theme.agentReview}</p>
                  </div>
                  <p className={styles.riskText}>
                    {copy.risk}: {theme.uncertainty}
                  </p>
                  <div className={styles.cardActions}>
                    <button
                      className={styles.primaryButton}
                      disabled={busy || theme.status === "stale"}
                      onClick={() => runThemeAction(theme, "select")}
                    >
                      <GitBranch size={15} />
                      {copy.select}
                    </button>
                    <button
                      className={styles.secondaryButton}
                      disabled={busy || theme.status === "stale"}
                      onClick={() => runThemeAction(theme, "theme-card")}
                    >
                      <FlaskConical size={15} />
                      {copy.themeCard}
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

            <aside className={styles.sideColumn}>
              <section className={styles.processPanel}>
            <div className={styles.stageRail}>
              {STAGES.map((stage, index) => {
                const StageIcon = stage.icon;
                const label =
                  stage.id === "broad"
                    ? copy.broad
                    : stage.id === "deep"
                      ? copy.deep
                      : stage.id === "evidence"
                        ? copy.evidence
                        : stage.id === "themes"
                          ? copy.themes
                          : copy.themeCard;
                const action =
                  stage.id === "broad"
                    ? () => runAction("run-broad-search")
                    : stage.id === "deep"
                      ? () => runAction("run-deep-search")
                      : stage.id === "evidence"
                        ? () => runAction("extract-evidence")
                        : stage.id === "themes"
                          ? () => runAction("generate-themes")
                          : selectedTheme
                            ? () => runThemeAction(selectedTheme, "theme-card")
                            : undefined;
                return (
                  <article key={stage.id} className={styles.stageCard}>
                    <div className={styles.stageIndex}>
                      <StageIcon size={16} />
                      <span>{String(index + 1).padStart(2, "0")}</span>
                    </div>
                    <div className={styles.stageBody}>
                      <div className={styles.stageHeader}>
                        <strong>{label}</strong>
                        <span>{stageStatus(stage.id, active)}</span>
                      </div>
                      <button
                        className={styles.secondaryButton}
                        disabled={busy || !activeSessionId || !action}
                        onClick={action}
                      >
                        <RefreshCw size={14} />
                        {stage.id === "card" ? copy.themeCard : copy.rerun}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
              </section>
            </aside>
          </>
        ) : null}
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
    const execution = asRecord(asRecord(run?.modelProfile).searchExecution);
    const sourceCounts = asRecord(execution.sourceCounts);
    const totalSources = sumRecordNumbers(sourceCounts);
    const queryCount = run?.queries.length ?? 0;
    const failedCount = numberFrom(execution.failedAttemptCount);
    const sources = active.sources.filter((item) => stage === "broad" || item.searchRunId === run?.runId);
    const sampleSource = sources[0];
    return {
      summary:
        stage === "broad"
          ? `已完成广撒网：${queryCount} 组查询，收集 ${totalSources} 条来源，${failedCount} 次失败。`
          : `已完成定向深搜：${queryCount} 组查询，收集 ${totalSources} 条来源，${failedCount} 次失败。`,
      items: [
        { label: copy.queries, value: `${queryCount}` },
        { label: copy.sources, value: `${totalSources}` },
        { label: copy.failed, value: `${failedCount}` },
        {
          label: copy.sample,
          value: sampleSource
            ? `${clip(sampleSource.title, 42)} · ${sourceKindLabel(sampleSource.kind, lang)}`
            : clip(run?.queries[0] || copy.pending, 54),
        },
      ],
    };
  }

  if (stage === "evidence") {
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

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
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
    return active.searchRuns.some((run) => run.phase === "broad" && run.status === "completed") ? "done" : "ready";
  }
  if (stage === "deep") {
    return active.searchRuns.some((run) => run.phase === "deep" && run.status === "completed") ? "done" : "ready";
  }
  if (stage === "evidence") {
    return active.evidence.length ? "done" : "ready";
  }
  if (stage === "themes") {
    return active.summary.candidateThemeCount ? "done" : "ready";
  }
  return active.themeCards.length ? "done" : "ready";
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
