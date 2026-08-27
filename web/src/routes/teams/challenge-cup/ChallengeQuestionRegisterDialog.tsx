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
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../../api/queryKeys";
import {
  publishChallengeQuestionRun,
  registerChallengeQuestionRun,
} from "../../../api/teamExperiment";
import { experimentPlanningStatusQueryKey } from "../experimentLoopModel";
import {
  observeQuestionOutputSchemaRejected,
  trackQuestionPublishSubmit,
  trackQuestionRegisterSubmit,
} from "../challengeCupTelemetry";
import {
  VButton,
  VCheckbox,
  VDialog,
  VInput,
  VStatusChip,
  VTabs,
  VTextarea,
} from "../../../components/vui";
import {
  challengeRecordStatusLabel,
  challengeValidationStatusLabel,
} from "./ChallengeQuestionDetailPrimitives";
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
  lang?: "zh" | "en";
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

function parseOutput(raw: string, lang: "zh" | "en" = "zh"): ParsedOutput {
  const isZh = lang === "zh";
  const trimmed = raw.trim();
  if (!trimmed) {
    return { ok: false, error: isZh ? "请先粘贴题目产出 JSON（schema v2）。" : "Paste the question output JSON (schema v2) first." };
  }
  let value: unknown;
  try {
    value = JSON.parse(trimmed);
  } catch (error) {
    return { ok: false, error: isZh ? `JSON 解析失败：${error instanceof Error ? error.message : String(error)}` : `JSON parse failed: ${error instanceof Error ? error.message : String(error)}` };
  }
  if (!isRecord(value)) {
    return { ok: false, error: isZh ? "产出必须是一个 JSON 对象。" : "The output must be a JSON object." };
  }
  if (value.schema_version !== 2) {
    return { ok: false, error: isZh ? "后端只接受 schema_version=2 的产出；v1 为只读历史格式。" : "Only schema_version=2 is accepted; v1 is a read-only legacy format." };
  }
  const identity = isRecord(value.identity) ? value.identity : value;
  const questionId = text(identity.question_id);
  const run = isRecord(value.run) ? value.run : {};
  const runId = text(run.run_id);
  if (!questionId || !runId) {
    return { ok: false, error: isZh ? "产出缺少 identity.question_id 或 run.run_id。" : "Output is missing identity.question_id or run.run_id." };
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
  lang = "zh",
}: ChallengeQuestionRegisterDialogProps) {
  const isZh = lang === "zh";
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

  const parsed = useMemo(() => parseOutput(outputText, lang), [outputText, lang]);

  // Bounded observation: surface one schema-rejection per dialog mount so the
  // raw log keeps evidence of schema drift / operator paste mistakes.
  const schemaRejectObservedRef = useRef(false);
  useEffect(() => {
    if (schemaRejectObservedRef.current || parsed.ok || !outputText.trim()) return;
    schemaRejectObservedRef.current = true;
    observeQuestionOutputSchemaRejected({
      teamId,
      outputLength: outputText.trim().length,
      parseError: parsed.error,
    });
  }, [parsed, outputText, teamId]);

  const mutation = useMutation({
    mutationFn: submitQuestionWrite,
    onMutate: (vars) => {
      const baseFields = {
        teamId,
        questionId: parsed.ok ? parsed.questionId : "",
        outputLength: outputText.trim().length,
        evidenceCount: parsed.ok ? parsed.evidenceCount : 0,
        citationsConfirmed,
        lineageRefCount: parseLineageRefs(lineageRefsText).length,
        parentRunId: parentRunIdInput.trim(),
      };
      return {
        telemetry: vars.mode === "publish"
          ? trackQuestionPublishSubmit({ ...baseFields, researchProjectId: researchProjectId.trim() })
          : trackQuestionRegisterSubmit(baseFields),
      };
    },
    onSuccess: async (data, _vars, context) => {
      context?.telemetry?.succeeded({
        questionId: data?.record?.questionId ?? "",
        runId: data?.record?.runId ?? "",
        idempotent: data?.idempotent === true,
        humanGatesApproved: data?.record?.humanGates?.approvedCount ?? 0,
      });
      try {
        globalThis.localStorage?.setItem(REGISTERED_BY_STORAGE_KEY, registeredBy.trim());
      } catch {
        // 记住登记人只是便利，存储不可用时静默降级
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.challengeQuestionRunStatus(teamId) });
      // The progress panel previously fetched the experiment planning status
      // under the run-status key; keep that refresh semantics now that the
      // panel uses the canonical planning key.
      await queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(teamId) });
      const affectedQuestionId = data?.record?.questionId || (parsed.ok ? parsed.questionId : "");
      if (affectedQuestionId) {
        await queryClient.invalidateQueries({
          queryKey: queryKeys.challengeQuestionRunDetail(teamId, affectedQuestionId),
        });
      }
    },
    onError: (error, _vars, context) => {
      context?.telemetry?.failed(error);
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
  const resultStatus = resultRecord?.status || "review_required";
  const title = isZh ? "登记 / 发布题目产出" : "Register / publish question output";

  const resultBlock = resultRecord ? (
    <div className={css.registerResult} data-vui="question-write-result" role="status">
      <div className={css.cardTopline}>
        <strong>
          {mode === "publish" ? (isZh ? "发布成功" : "Published") : (isZh ? "登记成功" : "Registered")}
          {mutation.data?.idempotent ? (isZh ? "（幂等：相同产出已登记过）" : " (idempotent: identical output already registered)") : ""}
        </strong>
        <VStatusChip tone={resultRecord.status === "approved" ? "accent" : "warning"}>
          {challengeRecordStatusLabel(resultStatus, isZh ? "zh" : "en")}
        </VStatusChip>
      </div>
      <div className={css.metadata}>
        <span>{resultRecord.questionId || "—"}</span>
        <span>run {resultRecord.runId || "—"}</span>
        <span>{isZh ? `H1–H4 已通过 ${resultRecord.humanGates?.approvedCount ?? 0}/4` : `H1–H4 approved ${resultRecord.humanGates?.approvedCount ?? 0}/4`}</span>
      </div>
      <div className={css.registerResultGrid}>
        <VStatusChip tone={validationTone(resultRecord.validation?.schemaValidation === undefined ? undefined : resultRecord.validation.schemaValidation === "passed")}>
          {isZh ? "结构校验" : "Schema"} {resultRecord.validation?.schemaValidation
            ? challengeValidationStatusLabel(resultRecord.validation.schemaValidation, isZh ? "zh" : "en")
            : "—"}
        </VStatusChip>
        <VStatusChip tone={validationTone(resultRecord.validation?.citationValidation === undefined ? undefined : resultRecord.validation.citationValidation === "passed")}>
          {isZh ? "引用" : "Citation"} {resultRecord.validation?.citationValidation
            ? challengeValidationStatusLabel(resultRecord.validation.citationValidation, isZh ? "zh" : "en")
            : "—"}
        </VStatusChip>
        <VStatusChip tone={validationTone(resultRecord.validation?.semanticValidation === undefined ? undefined : resultRecord.validation.semanticValidation === "passed")}>
          {isZh ? "语义" : "Semantic"} {resultRecord.validation?.semanticValidation
            ? challengeValidationStatusLabel(resultRecord.validation.semanticValidation, isZh ? "zh" : "en")
            : "—"}
        </VStatusChip>
        <VStatusChip tone={validationTone(resultRecord.validation?.officialModelCall)}>
          {isZh
            ? `官方模型调用 ${resultRecord.validation?.officialModelCall ? "是" : "否"}`
            : `Official model call ${resultRecord.validation?.officialModelCall ? "yes" : "no"}`}
        </VStatusChip>
      </div>
      <p className={css.registerHint}>
        {resultRecord.validation?.officialModelCall
          ? (isZh
            ? "该题已进入 H1–H4 人工审核流；在题目详情页提交审核结论后才会计入正式批准。"
            : "The question entered the H1–H4 human review flow; it counts as formally approved only after a review decision on the detail page.")
          : (isZh
            ? "登记已保存，但尚未满足人工审核条件：官方模型证据需先经发布（publish）晋升到团队级。请先发布该 run 的官方模型证据，再回到详情页提交审核。"
            : "Registration saved, but human review is not available yet: official-model evidence must be published to the team level first. Publish this run's evidence, then submit the review on the detail page.")}
      </p>
      <div className={css.registerActions}>
        {onOpenQuestion && resultQuestionId ? (
          <VButton
            type="button"
            variant="primary"
            density="compact"
            onPress={() => onOpenQuestion(resultQuestionId)}
          >
            {isZh ? "查看题目详情" : "Open question detail"}
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
          {isZh ? "继续登记下一份" : "Register another"}
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
      description={isZh
        ? "粘贴研究运行产出的题目 JSON（schema v2）；后端完成 schema / 引用 / 语义校验后写入 Program 台账，题目进入 H1–H4 人工审核。"
        : "Paste the question output JSON (schema v2) from a research run; after backend schema/citation/semantic validation it is written to the program ledger and enters H1–H4 human review."}
      size="lg"
      aria-label={title}
      footer={resultRecord ? (
        <VButton type="button" variant="secondary" density="compact" onPress={onClose}>
          {isZh ? "关闭" : "Close"}
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
            {isZh ? "取消" : "Cancel"}
          </VButton>
          <VButton
            type="button"
            variant="primary"
            density="compact"
            isDisabled={!canSubmit}
            isPending={mutation.isPending}
            disabledReason={
              !parsed.ok
                ? (isZh ? "先粘贴可通过解析的 schema v2 产出 JSON" : "Paste a parseable schema v2 output JSON first")
                : mode === "publish" && !publishBindingReady
                  ? (isZh ? "发布需要完整的研究项目证据绑定" : "Publishing requires the full research-project evidence binding")
                  : publishQuestionMismatch
                    ? (isZh ? "发布 questionId 必须与产出 identity.question_id 一致" : "Publish questionId must match the output identity.question_id")
                    : undefined
            }
            onPress={submit}
          >
            {mode === "publish" ? (isZh ? "发布产出" : "Publish output") : (isZh ? "登记产出" : "Register output")}
          </VButton>
        </>
      )}
    >
      <div className={css.registerDialog}>
        <VTabs
          density="compact"
          aria-label={isZh ? "写入方式" : "Write mode"}
          value={mode}
          onValueChange={(value) => {
            if (value === "register" || value === "publish") {
              setMode(value);
              mutation.reset();
            }
          }}
          items={[
            { id: "register", label: isZh ? "登记产出" : "Register" },
            { id: "publish", label: isZh ? "发布产出" : "Publish" },
          ]}
        />
        <p className={css.registerHint}>
          {mode === "register"
            ? (isZh
              ? "登记：把题目产出写入 Program 台账并记录校验结果，随后进入人工审核。"
              : "Register: write the question output to the program ledger with validation results, then enter human review.")
            : (isZh
              ? "发布：把研究项目中已获官方模型证据的产出晋升到 Program 台账；校验任一不过则整体失败。"
              : "Publish: promote an output with official model evidence in a research project to the program ledger; any failed validation fails the whole write.")}
        </p>

        {mode === "publish" ? (
          <div className={css.registerFields}>
            <label className={css.field}>
              <span>{isZh ? "研究项目 ID" : "Research project ID"}</span>
              <VInput
                aria-label={isZh ? "研究项目 ID" : "Research project ID"}
                value={researchProjectId}
                onChange={(event) => { setResearchProjectId(event.currentTarget.value); resetWriteState(); }}
                placeholder="project-sci-096"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>{isZh ? "题目 ID" : "Question ID"}</span>
              <VInput
                aria-label={isZh ? "题目 ID" : "Question ID"}
                value={questionId}
                onChange={(event) => { setQuestionId(event.currentTarget.value); resetWriteState(); }}
                placeholder="SCI-096"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>{isZh ? "任务 ID" : "Task ID"}</span>
              <VInput
                aria-label={isZh ? "任务 ID" : "Task ID"}
                value={taskId}
                onChange={(event) => { setTaskId(event.currentTarget.value); resetWriteState(); }}
                placeholder="stage-task-sci-096"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>{isZh ? "轮次 ID" : "Turn ID"}</span>
              <VInput
                aria-label={isZh ? "轮次 ID" : "Turn ID"}
                value={turnId}
                onChange={(event) => { setTurnId(event.currentTarget.value); resetWriteState(); }}
                placeholder="turn-sci-096"
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>{isZh ? "项目证据 ID" : "Project evidence ID"}</span>
              <VInput
                aria-label={isZh ? "项目证据 ID" : "Project evidence ID"}
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
            {isZh
              ? `发布 questionId 与产出 identity.question_id（${parsed.ok ? parsed.questionId : ""}）不一致。`
              : `Publish questionId does not match the output identity.question_id (${parsed.ok ? parsed.questionId : ""}).`}
          </div>
        ) : null}

        <label className={css.field}>
          <span>{isZh ? "题目产出 JSON（schema v2）" : "Question output JSON (schema v2)"}</span>
          <VTextarea
            aria-label={isZh ? "题目产出 JSON" : "Question output JSON"}
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
              {isZh
                ? `解析到 ${parsed.questionId} · run ${parsed.runId} · 证据 ${parsed.evidenceCount} 条`
                : `Parsed ${parsed.questionId} · run ${parsed.runId} · ${parsed.evidenceCount} evidence items`}
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
          {isZh ? "来源链接已逐条核对" : "Source links verified one by one"}
        </VCheckbox>
        <p className={css.registerHint}>
          {isZh
            ? "勾选后为产出中每条 evidence.source_url 生成 passed 引用检查；不勾选则后端记录 citationValidation=failed，题目不会进入「已验证」列表。"
            : "When checked, a passed citation check is generated for each evidence.source_url; otherwise the backend records citationValidation=failed and the question never enters the verified list."}
        </p>

        {mode === "register" ? (
          <div className={css.registerFields}>
            <label className={css.field}>
              <span>{isZh ? "父 Run ID（修订登记时填）" : "Parent run ID (for revisions)"}</span>
              <VInput
                aria-label={isZh ? "父 Run ID" : "Parent run ID"}
                value={parentRunIdInput}
                onChange={(event) => { setParentRunIdInput(event.currentTarget.value); resetWriteState(); }}
                placeholder={isZh ? "上一版 run_id" : "Previous run_id"}
                isDisabled={mutation.isPending}
              />
            </label>
            <label className={css.field}>
              <span>{isZh ? "血缘引用（可选，逗号分隔）" : "Lineage refs (optional, comma-separated)"}</span>
              <VInput
                aria-label={isZh ? "血缘引用" : "Lineage refs"}
                value={lineageRefsText}
                onChange={(event) => { setLineageRefsText(event.currentTarget.value); resetWriteState(); }}
                placeholder="evidence-id-1, evidence-id-2"
                isDisabled={mutation.isPending}
              />
            </label>
          </div>
        ) : null}

        <label className={css.field}>
          <span>{isZh ? "登记人（可选）" : "Registered by (optional)"}</span>
          <VInput
            aria-label={isZh ? "登记人" : "Registered by"}
            value={registeredBy}
            onChange={(event) => { setRegisteredBy(event.currentTarget.value); resetWriteState(); }}
            placeholder={isZh ? "你的名字" : "Your name"}
            isDisabled={mutation.isPending}
          />
        </label>

        {mutation.isError ? (
          <div className={css.missingLine} role="alert">
            {mutation.error instanceof Error ? mutation.error.message : (isZh ? "提交失败，请重试" : "Submit failed; please retry")}
          </div>
        ) : null}

        {resultBlock}
      </div>
    </VDialog>
  );
}
