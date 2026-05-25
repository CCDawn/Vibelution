import {
  Beaker,
  BookOpenCheck,
  BrainCircuit,
  FileCheck2,
  GitCompareArrows,
  Network,
  SearchCheck,
  Sparkles,
} from "lucide-react";

import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./ResearchRoute.module.css";

type ResearchStage = {
  id: string;
  title: string;
  status: string;
  detail: string;
  output: string;
};

type EvidenceItem = {
  title: string;
  source: string;
  signal: string;
  state: "ready" | "draft" | "blocked";
};

type OutputItem = {
  title: string;
  detail: string;
  count: string;
};

const COPY = {
  zh: {
    eyebrow: "Research Flow",
    title: "科研流程展示",
    subtitle: "先把研究链路摆清楚：问题进入、资料归档、假设拆分、实验设计、证据合成、输出沉淀。",
    objective: "当前目标",
    objectiveBody: "把一个模糊科研任务收束成可追踪的研究现场，后续再逐步接入论文检索、实验运行和报告生成。",
    status: "状态",
    statusBody: "前端展示版",
    boundary: "边界",
    boundaryBody: "不执行真实检索或实验",
    next: "下一步",
    nextBody: "确认流程语言与信息架构",
    pipeline: "流程主线",
    evidence: "证据面板",
    outputs: "产出区",
    risk: "风险与护栏",
    riskBody: "科研页先保持 advisory-only，不把未验证材料写入运行策略；每个结论都要能回到来源、实验或人工备注。",
    stages: [
      {
        id: "question",
        title: "问题定义",
        status: "输入",
        detail: "收集研究问题、约束、目标读者和成功标准。",
        output: "研究 brief",
      },
      {
        id: "sources",
        title: "资料归档",
        status: "整理",
        detail: "聚合论文、网页、数据集、历史实验和相关项目记忆。",
        output: "资料库",
      },
      {
        id: "hypothesis",
        title: "假设拆分",
        status: "建模",
        detail: "把大问题拆成可反驳假设、变量和对照条件。",
        output: "假设矩阵",
      },
      {
        id: "experiment",
        title: "实验设计",
        status: "计划",
        detail: "定义评测指标、样本、baseline、消融和失败判定。",
        output: "实验计划",
      },
      {
        id: "evidence",
        title: "证据合成",
        status: "审查",
        detail: "把引用、实验结果、反例和局限性归一到可追溯证据链。",
        output: "证据地图",
      },
      {
        id: "writing",
        title: "产出沉淀",
        status: "输出",
        detail: "生成报告大纲、论文段落、复现实验说明和下一轮问题。",
        output: "研究包",
      },
    ] satisfies ResearchStage[],
    evidenceItems: [
      {
        title: "文献矩阵",
        source: "论文 / 综述 / benchmark",
        signal: "主题、方法、指标和结论对齐",
        state: "draft",
      },
      {
        title: "实验账本",
        source: "本地运行 / 评测记录",
        signal: "参数、分数、失败样本和复现步骤",
        state: "blocked",
      },
      {
        title: "证据地图",
        source: "引用 / 表格 / 图 / 备注",
        signal: "每个主张都能追到证据来源",
        state: "ready",
      },
    ] satisfies EvidenceItem[],
    outputItems: [
      { title: "研究 brief", detail: "问题、范围、术语和验收口径", count: "01" },
      { title: "实验计划", detail: "变量、baseline、指标和失败条件", count: "02" },
      { title: "写作包", detail: "大纲、论断、引用和局限性", count: "03" },
    ] satisfies OutputItem[],
    stateLabels: {
      ready: "可用",
      draft: "草稿",
      blocked: "待接入",
    },
  },
  en: {
    eyebrow: "Research Flow",
    title: "Research Flow Preview",
    subtitle: "Make the research chain visible: question intake, source archive, hypotheses, experiment design, evidence synthesis, and durable output.",
    objective: "Current objective",
    objectiveBody: "Turn a vague research task into a traceable workspace before connecting paper search, experiment execution, and report generation.",
    status: "State",
    statusBody: "Frontend preview",
    boundary: "Boundary",
    boundaryBody: "No real search or experiment execution",
    next: "Next",
    nextBody: "Confirm workflow language and IA",
    pipeline: "Pipeline",
    evidence: "Evidence board",
    outputs: "Outputs",
    risk: "Risks and guardrails",
    riskBody: "This page stays advisory-only first. Unverified material should not change runtime policy, and every claim must trace back to a source, experiment, or human note.",
    stages: [
      {
        id: "question",
        title: "Question framing",
        status: "Intake",
        detail: "Collect the research question, constraints, target reader, and success criteria.",
        output: "Research brief",
      },
      {
        id: "sources",
        title: "Source archive",
        status: "Organize",
        detail: "Gather papers, webpages, datasets, prior experiments, and project memory.",
        output: "Source library",
      },
      {
        id: "hypothesis",
        title: "Hypothesis split",
        status: "Model",
        detail: "Break the broad question into falsifiable hypotheses, variables, and controls.",
        output: "Hypothesis matrix",
      },
      {
        id: "experiment",
        title: "Experiment design",
        status: "Plan",
        detail: "Define metrics, samples, baselines, ablations, and failure criteria.",
        output: "Experiment plan",
      },
      {
        id: "evidence",
        title: "Evidence synthesis",
        status: "Review",
        detail: "Normalize citations, results, counterexamples, and limitations into traceable evidence.",
        output: "Evidence map",
      },
      {
        id: "writing",
        title: "Output capture",
        status: "Publish",
        detail: "Produce report outlines, paper sections, reproduction notes, and next questions.",
        output: "Research packet",
      },
    ] satisfies ResearchStage[],
    evidenceItems: [
      {
        title: "Literature matrix",
        source: "Papers / surveys / benchmarks",
        signal: "Themes, methods, metrics, and conclusions aligned",
        state: "draft",
      },
      {
        title: "Experiment ledger",
        source: "Local runs / evaluation records",
        signal: "Parameters, scores, failures, and reproduction steps",
        state: "blocked",
      },
      {
        title: "Evidence map",
        source: "Citations / tables / figures / notes",
        signal: "Every claim can trace back to evidence",
        state: "ready",
      },
    ] satisfies EvidenceItem[],
    outputItems: [
      { title: "Research brief", detail: "Question, scope, terms, and acceptance bar", count: "01" },
      { title: "Experiment plan", detail: "Variables, baselines, metrics, and failure conditions", count: "02" },
      { title: "Writing packet", detail: "Outline, claims, citations, and limitations", count: "03" },
    ] satisfies OutputItem[],
    stateLabels: {
      ready: "Ready",
      draft: "Draft",
      blocked: "Pending",
    },
  },
};

const stageIcons = [SearchCheck, BookOpenCheck, BrainCircuit, Beaker, GitCompareArrows, FileCheck2];

function stateTone(state: EvidenceItem["state"]) {
  return state === "ready" ? "ready" : state === "draft" ? "draft" : "blocked";
}

export function ResearchRoute() {
  const { lang, t } = useAppI18n();
  const copy = COPY[lang];

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{t("researchPageTitle")}</h1>
          <p className={styles.subtitle}>{t("researchPageSubtitle")}</p>
        </div>
      </header>

      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.objective}</span>
          <strong>{copy.objectiveBody}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.status}</span>
          <strong>{copy.statusBody}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.boundary}</span>
          <strong>{copy.boundaryBody}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.next}</span>
          <strong>{copy.nextBody}</strong>
        </section>
      </div>

      <main className={styles.workspace}>
        <section className={styles.pipelinePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.pipeline}</p>
              <h2>{copy.title}</h2>
            </div>
            <span className={styles.countPill}>{copy.stages.length}</span>
          </div>
          <div className={styles.stageList}>
            {copy.stages.map((stage, index) => {
              const StageIcon = stageIcons[index] ?? Network;
              return (
                <article key={stage.id} className={styles.stageCard}>
                  <div className={styles.stageIndex}>
                    <StageIcon size={17} />
                    <span>{String(index + 1).padStart(2, "0")}</span>
                  </div>
                  <div className={styles.stageBody}>
                    <div className={styles.stageHeader}>
                      <strong>{stage.title}</strong>
                      <span>{stage.status}</span>
                    </div>
                    <p>{stage.detail}</p>
                    <code>{stage.output}</code>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <aside className={styles.sideColumn}>
          <section className={styles.evidencePanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.evidence}</p>
                <h2>{copy.evidence}</h2>
              </div>
              <Network size={18} />
            </div>
            <div className={styles.evidenceList}>
              {copy.evidenceItems.map((item) => (
                <article key={item.title} className={styles.evidenceCard}>
                  <div className={styles.evidenceHeader}>
                    <strong>{item.title}</strong>
                    <span className={`${styles.statePill} ${styles[`state_${stateTone(item.state)}`]}`}>
                      {copy.stateLabels[item.state]}
                    </span>
                  </div>
                  <p>{item.source}</p>
                  <span>{item.signal}</span>
                </article>
              ))}
            </div>
          </section>

          <section className={styles.outputPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.outputs}</p>
                <h2>{copy.outputs}</h2>
              </div>
              <Sparkles size={18} />
            </div>
            <div className={styles.outputList}>
              {copy.outputItems.map((item) => (
                <article key={item.title} className={styles.outputCard}>
                  <span>{item.count}</span>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.detail}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className={styles.guardrailPanel}>
            <div>
              <p className={styles.panelEyebrow}>{copy.risk}</p>
              <h2>{copy.risk}</h2>
            </div>
            <p>{copy.riskBody}</p>
          </section>
        </aside>
      </main>
    </section>
  );
}
