/**
 * Operator entry for registering or publishing one produced Challenge Cup
 * question output (schema v2) into the program ledger, so the question enters
 * the H1–H4 human review flow.
 *
 * The output JSON is produced outside this surface (research runs / agents).
 * The dialog pastes it verbatim, lets the backend run schema/citation/semantic
 * validation, and shows the recorded validation result before the question
 * appears in the progress panel. Register is the lenient ledger write; publish
 * additionally binds a research-project canonical model evidence and hard-fails
 * unless every validation passes.
 */
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../../api/queryKeys";
import {
  publishChallengeQuestionRun,
  registerChallengeQuestionRun,
} from "../../../api/teamExperiment";
import {
  VButton,
  VCheckbox,
  VDialog,
  VInput,
  VStatusChip,
  VTabs,
  VTextarea,
} from "../../../components/vui";
import css from "./ChallengeQuestionDetailPanel.styles";

type WriteMode = "register" | "publish";

export type ChallengeQuestionRegisterDialogProps = {
  teamId: string;
  initialMode?: WriteMode;
  /** Pre-filled parent run for revision registrations after needs_revision. */
  parentRunId?: string;
  /** Pre-filled publish binding / display question id. */
  questionIdHint?: string;
  onClose: () => void;
  onOpenQuestion?: (questionId: string) => void;
};

type WriteValidation = {
  schemaValidation?: string;
  citationValidation?: string;
  semanticValidation?: string;
  officialModelCall?: boolean;
};

type WriteRecord = {
  questionId?: string;
  runId?: string;
  status?: string;
  submissionEligible?: boolean;
  validation?: WriteValidation;
  humanGates?: { approvedCount?: number; allApproved?: boolean };
};

type WriteResponse = {
  record?: WriteRecord;
  idempotent?: boolean;
  humanReviewRequired?: boolean;
};

type ParsedOutput =
  | {
      ok: true;
      output: Record<string, unknown>;
      questionId: string;
      runId: string;
      evidenceCount: number;
    }
  | { ok: false; error: string };

const REGISTERED_BY_STORAGE_KEY = "vibelution.challenge-question-registered-by";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function parseOutput(raw: string): ParsedOutput {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { ok: false, error: "请先粘贴题目产出 JSON（schema v2）。" };
  }
  let value: unknown;
  try {
    value = JSON.parse(trimmed);
  } catch (error) {
    return { ok: false, error: `JSON 解析失败：${error instanceof Error ? error.message : String(error)}` };
  }
  if (!isRecord(value)) {
    return { ok: false, error: "产出必须是一个 JSON 对象。" };
  }
  if (value.schema_version !== 2) {
    return { ok: false, error: "后端只接受 schema_version=2 的产出；v1 为只读历史格式。" };
  }
  const identity = isRecord(value.identity) ? value.identity : value;
  const questionId = text(identity.question_id);
  const run = isRecord(value.run) ? value.run : {};
  const runId = text(run.run_id);
  if (!questionId || !runId) {
    return { ok: false, error: "产出缺少 identity.question_id 或 run.run_id。" };
  }
  const evidence = Array.isArray(value.evidence) ? value.evidence : [];
  return { ok: true, output: value, questionId, runId, evidenceCount: evidence.length };
}

function buildCitationChecks(output: Record<string, unknown>): Array<{ sourceUrl: string; status: string }> {
  const evidence = Array.isArray(output.evidence) ? output.evidence : [];
  const checks: Array<{ sourceUrl: string; status: string }> = [];
  for (const item of evidence) {
    if (!isRecord(item)) continue;
    const sourceUrl = text(item.source_url);
    if (sourceUrl) checks.push({ sourceUrl, status: "passed" });
  }
  return checks;
}

function parseLineageRefs(raw: string): string[] {
  const refs: string[] = [];
  for (const item of raw.split(/[\s,]+/)) {
    const normalized = item.trim();
    if (normalized && !refs.includes(normalized)) refs.push(normalized);
    if (refs.length >= 64) break;
  }
  return refs;
}

function validationTone(passed: boolean | undefined): "success" | "danger" | "neutral" {
  if (passed === undefined) return "neutral";
  return passed ? "success" : "danger";
}

async function submitQuestionWrite(vars: {
  mode: WriteMode;
  teamId: string;
  body: Record<string, unknown>;
}): Promise<WriteResponse> {
  if (vars.mode === "publish") {
    return publishChallengeQuestionRun<WriteResponse>(vars.teamId, vars.body);
  }
  return registerChallengeQuestionRun<WriteResponse>(vars.teamId, vars.body);
}

export function ChallengeQuestionRegisterDialog({
  teamId,
  initialMode = "register",
  parentRunId = "",
  questionIdHint = "",
  onClose,
  onOpenQuestion,
}: ChallengeQuestionRegisterDialogProps) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<WriteMode>(initialMode);
  const [outputText, setOutputText] = useState("");
  const [registeredBy, setRegisteredBy] = useState(() => {
    try {
      return globalThis.localStorage?.getItem(REGISTERED_BY_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [citationsConfirmed, setCitationsConfirmed] = useState(false);
  const [parentRunIdInput, setParentRunIdInput] = useState(parentRunId);
  const [lineageRefsText, setLineageRefsText] = useState("");
  const [researchProjectId, setResearchProjectId] = useState("");
  const [questionId, setQuestionId] = useState(questionIdHint);
  const [taskId, setTaskId] = useState("");
  const [turnId, setTurnId] = useState("");
  const [projectEvidenceId, setProjectEvidenceId] = useState("");

  const parsed = useMemo(() => parseOutput(outputText), [outputText]);

  const mutation = useMutation({
    mutationFn: submitQuestionWrite,
    onSuccess: async (data) => {
      try {
        globalThis.localStorage?.setItem(REGISTERED_BY_STORAGE_KEY, registeredBy.trim());
      } catch {
        // 记住登记人只是便利，存储不可用时静默降级
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.challengeQuestionRunStatus(teamId) });
      const affectedQuestionId = data?.record?.questionId || (parsed.ok ? parsed.questionId : "");
      if (affectedQuestionId) {
        await queryClient.invalidateQueries({
          queryKey: queryKeys.challengeQuestionRunDetail(teamId, affectedQuestionId),
        });
      }
    },
  });

  const publishBindingReady = Boolean(
    researchProjectId.trim() && questionId.trim() && taskId.trim() && turnId.trim() && projectEvidenceId.trim(),
  );
  const publishQuestionMismatch = Boolean(
    mode === "publish" && parsed.ok && questionId.trim()
      && parsed.questionId.toUpperCase() !== questionId.trim().toUpperCase(),
  );
  const canSubmit = Boolean(
    parsed.ok
      && !mutation.isPending
      && (mode === "register" || publishBindingReady)
      && !publishQuestionMismatch,
  );

  const resetWriteState = () => {
    if (mutation.isSuccess || mutation.isError) mutation.reset();
  };

  const submit = () => {
    if (!parsed.ok || !canSubmit) return;
    const body: Record<string, unknown> = {
      output: parsed.output,
      citationChecks: citationsConfirmed ? buildCitationChecks(parsed.output) : [],
      registeredBy: registeredBy.trim(),
      parentRunId: parentRunIdInput.trim(),
      lineageRefs: parseLineageRefs(lineageRefsText),
    };
    if (mode === "publish") {
      body.researchProjectId = researchProjectId.trim();
      body.questionId = questionId.trim();
      body.taskId = taskId.trim();
      body.turnId = turnId.trim();
      body.projectEvidenceId = projectEvidenceId.trim();
    }
    mutation.mutate({ mode, teamId, body });
  };

  const resultRecord = mutation.isSuccess ? mutation.data?.record : undefined;
  const resultQuestionId = resultRecord?.questionId || (parsed.ok ? parsed.questionId : "");
  const title = "登记 / 发布题目产出";

  const resultBlock = resultRecord ? (
    <div className={css.registerResult} data-vui="question-write-result" role="status">
      <div className={css.cardTopline}>
        <strong>{mode === "publish" ? "发布成功" : "登记成功"}{mutation.data?.idempotent ? "（幂等：相同产出已登记过）" : ""}</strong>
        <VStatusChip tone={resultRecord.status === "approved" ? "accent" : "warning"}>
          {resultRecord.status || "review_required"}
        </VStatusChip>
      </div>
      <div className={css.metadata}>
        <span>{resultRecord.questionId || "—"}</span>
        <span>run {resultRecord.runId || "—"}</span>
        <span>H1–H4 已通过 {resultRecord.humanGates?.approvedCount ?? 0}/4</span>
      </div>
      <div className={css.registerResultGrid}>
        <VStatusChip tone={validationTone(resultRecord.validation?.schemaValidation === undefined ? undefined : resultRecord.validation.schemaValidation === "passed")}>
          Schema {resultRecord.validation?.schemaValidation ?? "—"}
        </VStatusChip>
        <VStatusChip tone={validationTone(resultRecord.validation?.citationValidation === undefined ? undefined : resultRecord.validation.citationValidation === "passed")}>
          引用 {resultRecord.validation?.citationValidation ?? "—"}
        </VStatusChip>
        <VStatusChip tone={validationTone(resultRecord.validation?.semanticValidation === undefined ? undefined : resultRecord.validation.semanticValidation === "passed")}>
          语义 {resultRecord.validation?.semanticValidation ?? "—"}
        </VStatusChip>
        <VStatusChip tone={validationTone(resultRecord.validation?.officialModelCall)}>
          官方模型调用 {resultRecord.validation?.officialModelCall ? "是" : "否"}
        </VStatusChip>
      </div>
      <p className={css.registerHint}>
        该题已进入 H1–H4 人工审核流；在题目详情页提交审核结论后才会计入正式批准。
      </p>
      <div className={css.registerActions}>
        {onOpenQuestion && resultQuestionId ? (
          <VButton
            type="button"
            variant="primary"
            density="compact"
            onPress={() => onOpenQuestion(resultQuestionId)}
          >
            查看题目详情
          </VButton>
        ) : null}
        <VButton
          type="button"
          variant="secondary"
          density="compact"
          onPress={() => {
            setOutputText("");
            setCitationsConfirmed(false);
            mutation.reset();
          }}
        >
          继续登记下一份
        </VButton>
      </div>
    </div>
  ) : null;

  return (
    <VDialog
      open
      onOpenChange={(open) => {
        if (!open && !mutation.isPending) onClose();
      }}
      title={title}
      description="粘贴研究运行产出的题目 JSON（schema v2）；后端完成 schema / 引用 / 语义校验后写入 Program 台账，题目进入 H1–H4 人工审核。"
      size="lg"
      aria-label={title}
      footer={resultRecord ? (
        <VButton type="button" variant="secondary" density="compact" onPress={onClose}>
          关闭
        </VButton>
      ) : (
        <>
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            isDisabled={mutation.isPending}
            onPress={onClose}
          >
            取消
          </VButton>
          <VButton
            type="button"
            variant="primary"
            density="compact"
            isDisabled={!canSubmit}
            isPending={mutation.isPending}
            disabledReason={
              !parsed.ok
                ? "先粘贴可通过解析的 schema v2 产出 JSON"
                : mode === "publish" && !publishBindingReady
                  ? "发布需要完整的研究项目证据绑定"
                  : publishQuestionMismatch
                    ? "发布 questionId 必须与产出 identity.question_id 一致"
                    : undefined
            }
            onPress={submit}
          >
            {mode === "publish" ? "发布产出" : "登记产出"}
          </VButton>
        </>
      )}
    >
      <div className={css.registerDialog}>
        <VTabs
          density="compact"
          aria-label="写入方式"
          value={mode}
          onValueChange={(value) => {
            if (value === "register" || value === "publish") {
              setMode(value);
              mutation.reset();
            }
          }}
          items={[
            { id: "register", label: "登记产出" },
            { id: "publish", label: "发布产出" },
          ]}
        />
        <p className={css.registerHint}>
          {mode === "register"
            ? "登记：把题目产出写入 Program 台账并记录校验结果，随后进入人工审核。"
            : "发布：把研究项目中已获官方模型证据的产出晋升到 Program 台账；校验任一不过则整体失败。"}
        </p>

        {mode === "publish" ? (
          <div className={css.registerFields}>
            <label className={css.field}>
              <span>研究项目 ID</span>
              <VInput
                aria-label="研究项目 ID"
                value={researchProjectId}
                onChange={(event) => { setResearchProjectId(event.currentTarget.value); resetWriteState(); }}
                placeholder="project-sci-096"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>题目 ID</span>
              <VInput
                aria-label="题目 ID"
                value={questionId}
                onChange={(event) => { setQuestionId(event.currentTarget.value); resetWriteState(); }}
                placeholder="SCI-096"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>任务 ID</span>
              <VInput
                aria-label="任务 ID"
                value={taskId}
                onChange={(event) => { setTaskId(event.currentTarget.value); resetWriteState(); }}
                placeholder="stage-task-sci-096"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>轮次 ID</span>
              <VInput
                aria-label="轮次 ID"
                value={turnId}
                onChange={(event) => { setTurnId(event.currentTarget.value); resetWriteState(); }}
                placeholder="turn-sci-096"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>项目证据 ID</span>
              <VInput
                aria-label="项目证据 ID"
                value={projectEvidenceId}
                onChange={(event) => { setProjectEvidenceId(event.currentTarget.value); resetWriteState(); }}
                placeholder="model-evidence-…"
                isDisabled={mutation.isPending}
              />
            </label>
          </div>
        ) : null}
        {publishQuestionMismatch ? (
          <div className={css.missingLine} role="alert">
            发布 questionId 与产出 identity.question_id（{parsed.ok ? parsed.questionId : ""}）不一致。
          </div>
        ) : null}

        <label className={css.field}>
          <span>题目产出 JSON（schema v2）</span>
          <VTextarea
            aria-label="题目产出 JSON"
            value={outputText}
            onChange={(event) => { setOutputText(event.currentTarget.value); resetWriteState(); }}
            placeholder='{"schema_version": 2, "identity": {"question_id": "SCI-096", …}, "run": {"run_id": …}, …}'
            minRows={8}
            spellCheck={false}
            isDisabled={mutation.isPending}
          />
        </label>
        {outputText.trim() ? (
          parsed.ok ? (
            <div className={css.registerPreview}>
              解析到 {parsed.questionId} · run {parsed.runId} · 证据 {parsed.evidenceCount} 条
            </div>
          ) : (
            <div className={css.missingLine} role="alert">{parsed.error}</div>
          )
        ) : null}

        <VCheckbox
          isSelected={citationsConfirmed}
          onChange={(next) => { setCitationsConfirmed(next); resetWriteState(); }}
          isDisabled={mutation.isPending}
        >
          来源链接已逐条核对
        </VCheckbox>
        <p className={css.registerHint}>
          勾选后为产出中每条 evidence.source_url 生成 passed 引用检查；不勾选则后端记录 citationValidation=failed，题目不会进入「已验证」列表。
        </p>

        {mode === "register" ? (
          <div className={css.registerFields}>
            <label className={css.field}>
              <span>父 Run ID（修订登记时填）</span>
              <VInput
                aria-label="父 Run ID"
                value={parentRunIdInput}
                onChange={(event) => { setParentRunIdInput(event.currentTarget.value); resetWriteState(); }}
                placeholder="上一版 run_id"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>血缘引用（可选，逗号分隔）</span>
              <VInput
                aria-label="血缘引用"
                value={lineageRefsText}
                onChange={(event) => { setLineageRefsText(event.currentTarget.value); resetWriteState(); }}
                placeholder="evidence-id-1, evidence-id-2"
                isDisabled={mutation.isPending}
              />
            </label>
          </div>
        ) : null}

        <label className={css.field}>
          <span>登记人（可选）</span>
          <VInput
            aria-label="登记人"
            value={registeredBy}
            onChange={(event) => { setRegisteredBy(event.currentTarget.value); resetWriteState(); }}
            placeholder="你的名字"
            isDisabled={mutation.isPending}
          />
        </label>

        {mutation.isError ? (
          <div className={css.missingLine} role="alert">
            {mutation.error instanceof Error ? mutation.error.message : "提交失败，请重试"}
          </div>
        ) : null}

        {resultBlock}
      </div>
    </VDialog>
  );
}
