import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAgentConfigWorkspace } from "../../api/agents";
import { previewForkAIBacktest, startAIBacktest } from "../../api/financialBacktests";
import { queryKeys } from "../../api/queryKeys";
import type { AIBacktestForkPreviewRequest, AIBacktestParameterKey, AIBacktestPreview, AIBacktestRun } from "../../api/types/financialBacktests";
import type { AgentModelChoice } from "../../api/types/agents";
import { VButton, VDialog, VInput, VSelect, VStateSurface, VTextarea, VSurface } from "../../components/vui";
import { AI_BACKTEST_PARAMETER_OPTIONS, readAIBacktestParameterValue } from "./financialBacktestParameters";
import styles from "./FinanceAIBacktest.styles";

type Props = {
  agentId: string;
  source: AIBacktestRun;
  open: boolean;
  disabled: boolean;
  zh: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (run: AIBacktestRun) => Promise<void>;
};

const eligibleModels = (choices: AgentModelChoice[]) =>
  choices.filter((choice) => choice.runtimeSelectable && choice.slotCompatibility?.dialogue?.allowed === true);
const NO_MODEL_SELECTION = "__choose_model__";
const NO_PARAMETER_SELECTION = "__choose_parameter__";

type ForkMode = "strategy_model" | "parameter";

function symbolsForRun(run: Pick<AIBacktestRun, "symbol" | "symbols">) {
  return run.symbols?.length ? run.symbols : run.symbol ? [run.symbol] : [];
}

function sameSymbols(left: string[], right: string[]) {
  const a = left.map((item) => item.toLowerCase()).sort();
  const b = right.map((item) => item.toLowerCase()).sort();
  return a.length === b.length && a.every((item, index) => item === b[index]);
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请重试";
}

export function FinanceBacktestForkDialog({ agentId, source, open, disabled, zh, onOpenChange, onStarted }: Props) {
  const workspace = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: ({ signal }) => fetchAgentConfigWorkspace({ includeRuntime: false, signal }),
    enabled: open,
    staleTime: 60_000,
    retry: false,
  });
  const candidates = useMemo(() => eligibleModels(workspace.data?.agentModelChoices ?? []), [workspace.data?.agentModelChoices]);
  const sourceModelAvailable = candidates.some((model) => model.modelId === source.modelId);
  const [strategy, setStrategy] = useState("");
  const [modelId, setModelId] = useState(NO_MODEL_SELECTION);
  const [maxTokens, setMaxTokens] = useState(source.maxTokens);
  const [forkMode, setForkMode] = useState<ForkMode>("strategy_model");
  const [parameterKey, setParameterKey] = useState<AIBacktestParameterKey | typeof NO_PARAMETER_SELECTION>(NO_PARAMETER_SELECTION);
  const [parameterValue, setParameterValue] = useState("");
  const [preview, setPreview] = useState<AIBacktestPreview | null>(null);
  const [pending, setPending] = useState<"preview" | "start" | "">("");
  const [error, setError] = useState("");
  const gate = useRef(false);
  const generation = useRef(0);
  const operation = useRef<symbol | null>(null);
  const modelChosen = useRef(false);
  const startRequest = useRef({ previewId: "", id: "" });
  const mounted = useRef(true);
  const sourceSymbols = symbolsForRun(source);
  const selectedParameter = AI_BACKTEST_PARAMETER_OPTIONS.find((item) => item.id === parameterKey);
  const selectedParameterValue = Number(parameterValue);
  const sourceParameterValue = parameterKey === NO_PARAMETER_SELECTION ? null : readAIBacktestParameterValue(source.params, parameterKey);
  const parameterValueValid = Boolean(
    selectedParameter
    && parameterValue.trim() !== ""
    && Number.isFinite(selectedParameterValue)
    && selectedParameterValue >= selectedParameter.min
    && selectedParameterValue <= selectedParameter.max
    && (!selectedParameter.choices || selectedParameter.choices.includes(selectedParameterValue))
    && (sourceParameterValue === null || selectedParameterValue !== sourceParameterValue),
  );
  const valid = Boolean(
    (forkMode === "parameter"
      ? parameterValueValid && Boolean(source.params?.strategy?.trim()) && candidates.some((model) => model.modelId === source.modelId)
      : strategy.trim() && strategy.length <= 4000 && candidates.some((model) => model.modelId === modelId))
    && Number.isInteger(maxTokens)
    && maxTokens >= 1000
    && maxTokens <= 2_000_000,
  );
  const busy = Boolean(pending);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    generation.current += 1;
    operation.current = null;
    gate.current = false;
    setPending("");
    setStrategy(source.params?.strategy ?? "");
    setModelId(NO_MODEL_SELECTION);
    setMaxTokens(source.maxTokens);
    setForkMode("strategy_model");
    setParameterKey(NO_PARAMETER_SELECTION);
    setParameterValue("");
    setPreview(null);
    setError("");
    modelChosen.current = false;
    startRequest.current = { previewId: "", id: "" };
  }, [open, source.runId]);

  useEffect(() => {
    if (!open || !workspace.data || modelChosen.current) return;
    setModelId(candidates.some((model) => model.modelId === source.modelId) ? source.modelId : NO_MODEL_SELECTION);
  }, [open, workspace.data, candidates, source.modelId]);

  function editStrategy(value: string) {
    generation.current += 1;
    setStrategy(value);
    setPreview(null);
    setError("");
  }

  function editModel(value: string) {
    modelChosen.current = true;
    generation.current += 1;
    setModelId(value);
    setPreview(null);
    setError("");
  }

  function editMaxTokens(value: number) {
    generation.current += 1;
    setMaxTokens(value);
    setPreview(null);
    setError("");
  }

  function editForkMode(value: ForkMode) {
    generation.current += 1;
    setForkMode(value);
    if (value === "parameter") {
      setStrategy(source.params?.strategy ?? "");
      setModelId(candidates.some((model) => model.modelId === source.modelId) ? source.modelId : NO_MODEL_SELECTION);
      setParameterKey(NO_PARAMETER_SELECTION);
      setParameterValue("");
    }
    setPreview(null);
    setError("");
  }

  function editParameterKey(value: AIBacktestParameterKey | typeof NO_PARAMETER_SELECTION) {
    generation.current += 1;
    setParameterKey(value);
    const metadata = AI_BACKTEST_PARAMETER_OPTIONS.find((item) => item.id === value);
    const sourceValue = metadata ? readAIBacktestParameterValue(source.params, metadata.id) : null;
    setParameterValue(metadata ? String(sourceValue ?? (metadata.id === "maxParticipationPct" ? 1 : metadata.choices?.[0] ?? metadata.min)) : "");
    setPreview(null);
    setError("");
  }

  function editParameterValue(value: string) {
    generation.current += 1;
    setParameterValue(value);
    setPreview(null);
    setError("");
  }

  async function perform(kind: "preview" | "start", work: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true;
    const owner = Symbol(kind);
    operation.current = owner;
    setPending(kind);
    setError("");
    try {
      await work();
    } catch (cause) {
      if (mounted.current && operation.current === owner) setError(errorMessage(cause));
    } finally {
      if (operation.current === owner) {
        gate.current = false;
        operation.current = null;
        if (mounted.current) setPending("");
      }
    }
  }

  async function createPreview() {
    if (!valid || disabled || workspace.isPending) return;
    const expectedGeneration = generation.current;
    const override: AIBacktestForkPreviewRequest = forkMode === "parameter"
      ? { [parameterKey]: selectedParameterValue } as AIBacktestForkPreviewRequest
      : { strategy: strategy.trim(), modelId, maxTokens };
    const data = await previewForkAIBacktest(agentId, source.runId, override);
    if (!mounted.current || generation.current !== expectedGeneration) return;
    if (data.agentId !== agentId || !sameSymbols(symbolsForRun(data), sourceSymbols)) {
      throw new Error(zh ? "副本预检返回了不匹配的智能体或股票组合" : "Fork preview returned a different agent or asset set");
    }
    if (!source.dataHash || data.dataHash !== source.dataHash) {
      throw new Error(zh ? "副本没有复用源回测的冻结行情数据，不能继续" : "Fork preview did not reuse the source run's frozen market data");
    }
    if (forkMode === "parameter") {
      const sourceParams = source.params;
      const previewParams = data.params;
      const otherParameterMismatch = AI_BACKTEST_PARAMETER_OPTIONS.some((item) => item.id !== parameterKey
        && readAIBacktestParameterValue(sourceParams, item.id) !== readAIBacktestParameterValue(previewParams, item.id));
      if (
        !sourceParams
        || !previewParams
        || data.modelId !== source.modelId
        || data.maxTokens !== source.maxTokens
        || previewParams.strategy !== sourceParams.strategy
        || data.researchInput !== (source.researchInput ?? "price_only")
        || (data.researchHash ?? null) !== (source.researchHash ?? null)
        || (data.outOfSampleStartDate ?? null) !== (source.outOfSampleStartDate ?? null)
        || otherParameterMismatch
        || readAIBacktestParameterValue(previewParams, parameterKey as AIBacktestParameterKey) !== selectedParameterValue
      ) {
        throw new Error(zh ? "参数预检改变了模型、策略或其他冻结输入，不能作为单参数对照" : "Parameter preview changed the model, strategy, or another frozen input");
      }
    }
    setPreview(data);
  }

  async function startFork() {
    if (!preview?.canStart || disabled || Date.parse(preview.expiresAt) <= Date.now()) return;
    const expectedAgentId = agentId;
    const expectedSourceRunId = source.runId;
    const expectedGeneration = generation.current;
    if (startRequest.current.previewId !== preview.previewId) {
      startRequest.current = { previewId: preview.previewId, id: crypto.randomUUID() };
    }
    const run = await startAIBacktest(agentId, preview.previewId, startRequest.current.id);
    if (!mounted.current || generation.current !== expectedGeneration || agentId !== expectedAgentId || source.runId !== expectedSourceRunId) return;
    if (run.agentId !== agentId || !sameSymbols(symbolsForRun(run), sourceSymbols) || run.dataHash !== source.dataHash) {
      throw new Error(zh ? "副本启动结果与源回测的冻结数据不匹配" : "Started fork does not match the source run's frozen data");
    }
    await onStarted(run);
    setPreview(null);
    onOpenChange(false);
  }

  const modelOptions = candidates.map((model) => ({
    id: model.modelId,
    label: model.providerLabel ? model.providerLabel + " · " + model.label : model.label,
  }));
  modelOptions.unshift({ id: NO_MODEL_SELECTION, label: zh ? "明确选择可用模型" : "Choose an available model" });

  return (
    <VDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          generation.current += 1;
          operation.current = null;
          gate.current = false;
          setPending("");
          setPreview(null);
          setError("");
        }
        onOpenChange(next);
      }}
      title={zh ? "用同一份数据创建对照回测" : "Create a same-data comparison run"}
      description={forkMode === "parameter"
        ? (zh ? "每次只改一个参数；策略与模型保持源值。每条候选单独预检，并由你逐条点击开始，不会批量调用模型。" : "Change one parameter while preserving strategy and model. Preview and explicitly start each candidate one at a time; runs never auto-call in a batch.")
        : (zh ? "复制源任务冻结的行情、区间、样本外边界、资金、费用和频率；策略、模型与 Token 预算可单独调整。预检不调用模型。" : "Reuse frozen market data, dates, holdout boundary, capital, fees and frequency. Strategy, model and token budget can change. Preview makes no model call.")}
      footer={
        <>
          <VButton variant="secondary" isDisabled={busy} onPress={() => onOpenChange(false)}>{zh ? "关闭" : "Close"}</VButton>
          <VButton
            variant="secondary"
            isPending={pending === "preview"}
            isDisabled={busy || disabled || !valid || workspace.isPending}
            onPress={() => void perform("preview", createPreview)}
          >
            {zh ? "同数据预检" : "Preview same data"}
          </VButton>
          <VButton
            variant="primary"
            isPending={pending === "start"}
            isDisabled={busy || disabled || !preview?.canStart || Date.parse(preview?.expiresAt ?? "1970-01-01") <= Date.now()}
            onPress={() => void perform("start", startFork)}
          >
            {zh ? "开始对照回测" : "Start comparison run"}
          </VButton>
        </>
      }
    >
      <div className={styles.panel}>
        <p className={styles.note}>{zh ? "源回测" : "Source run"} {source.runId} · {sourceSymbols.join(" / ") || "—"} · {zh ? "冻结数据" : "Frozen data"} {source.dataHash?.slice(0, 12) || "—"}</p>
        <label className={styles.field}>
          {zh ? "副本用途" : "Fork purpose"}
          <VSelect
            aria-label={zh ? "回测副本用途" : "Fork purpose"}
            selectedKey={forkMode}
            isDisabled={busy}
            options={[
              { id: "strategy_model", label: zh ? "策略 / 模型对照" : "Strategy / model comparison" },
              { id: "parameter", label: zh ? "单参数敏感性" : "Single-parameter sensitivity" },
            ]}
            onSelectionChange={(key) => editForkMode(String(key ?? "strategy_model") as ForkMode)}
          />
        </label>
        {forkMode === "parameter" ? (
          <div className={styles.row}>
            <label className={styles.field}>
              {zh ? "变化参数" : "Parameter to vary"}
              <VSelect
                aria-label={zh ? "参数敏感性目标" : "Parameter sensitivity target"}
                selectedKey={parameterKey}
                isDisabled={busy}
                options={[
                  { id: NO_PARAMETER_SELECTION, label: zh ? "选择一个参数" : "Choose one parameter" },
                  ...AI_BACKTEST_PARAMETER_OPTIONS.map((item) => ({ id: item.id, label: item.label[zh ? "zh" : "en"] })),
                ]}
                onSelectionChange={(key) => editParameterKey(String(key ?? NO_PARAMETER_SELECTION) as AIBacktestParameterKey | typeof NO_PARAMETER_SELECTION)}
              />
            </label>
            {selectedParameter ? (
              <label className={styles.field}>
                {selectedParameter.label[zh ? "zh" : "en"]}
                {selectedParameter.choices ? (
                  <VSelect
                    aria-label={zh ? "参数敏感性取值" : "Parameter sensitivity value"}
                    selectedKey={parameterValue}
                    isDisabled={busy}
                    options={selectedParameter.choices.map((item) => ({ id: String(item), label: zh ? `${item} 个交易日` : `${item} sessions` }))}
                    onSelectionChange={(key) => editParameterValue(String(key ?? ""))}
                  />
                ) : (
                  <VInput
                    aria-label={zh ? "参数敏感性取值" : "Parameter sensitivity value"}
                    type="number"
                    min={selectedParameter.min}
                    max={selectedParameter.max}
                    step={selectedParameter.step}
                    value={parameterValue}
                    disabled={busy}
                    onChange={(event) => editParameterValue(event.target.value)}
                  />
                )}
              </label>
            ) : null}
            {parameterKey === "maxParticipationPct" && sourceParameterValue === null ? (
              <span className={styles.note}>{zh ? "源记录未设成交量参与率上限；填写数值会为新运行新增该限制。" : "The legacy source has no volume cap; a numeric value adds one to the new run."}</span>
            ) : null}
          </div>
        ) : null}
        {forkMode === "strategy_model" ? (
          <>
            <label className={styles.field}>
              {zh ? "新策略指令" : "Strategy instruction"}
              <VTextarea aria-label="对照回测策略指令" value={strategy} maxLength={4000} disabled={busy} onChange={(event) => editStrategy(event.target.value)} />
            </label>
            <div className={styles.row}>
              <label className={styles.field}>
                {zh ? "执行模型" : "Execution model"}
                <VSelect
                  aria-label="对照回测模型"
                  placeholder={zh ? "明确选择可用模型" : "Choose an available model"}
                  selectedKey={modelId}
                  isDisabled={busy || workspace.isPending || candidates.length === 0}
                  options={modelOptions}
                  onSelectionChange={(key) => editModel(String(key ?? ""))}
                />
              </label>
              <label className={styles.field}>
                {zh ? "Token 预算" : "Token budget"}
                <VInput aria-label="对照回测Token预算" type="number" min={1000} max={2_000_000} step={1000} value={String(maxTokens)} disabled={busy} onChange={(event) => editMaxTokens(Number(event.target.value))} />
              </label>
            </div>
            {maxTokens !== source.maxTokens ? <VStateSurface tone="info" density="compact" title={zh ? "Token预算与源回测不同；共同参数校验会判为不可比。" : "A different token budget changes shared assumptions, so this run will not pass the same-parameter comparison check."} /> : null}
          </>
        ) : (
          <p className={styles.note}>{zh ? `沿用源策略、模型与 Token 预算；模型：${source.modelId}。` : `Source strategy, model and token budget are preserved; model: ${source.modelId}.`}</p>
        )}
        {workspace.isPending ? <VStateSurface tone="loading" density="compact" busy title={zh ? "读取当前智能体可用模型" : "Loading models available to this agent"} /> : null}
        {workspace.isError ? <VStateSurface tone="error" density="compact" title={workspace.error.message} actions={<VButton onPress={() => void workspace.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
        {workspace.data && !sourceModelAvailable ? (
          <VStateSurface tone="info" density="compact" title={zh ? "源模型当前不可用于对话回测，请明确选择一个可用模型；系统不会自动替换。" : "The source model is not selectable for dialogue backtests. Choose an available model explicitly; no automatic substitution will occur."} />
        ) : null}
        {workspace.data && candidates.length === 0 ? <VStateSurface tone="error" density="compact" title={zh ? "当前没有同时满足运行可选和对话兼容条件的模型。" : "No model is both runtime-selectable and dialogue-compatible."} /> : null}
        {preview ? (
          <VSurface tone="panel" padding="compact" className={styles.panel}>
            <div className={styles.row}>
              <span>{zh ? "复用行情" : "Frozen data"} {preview.dataHash === source.dataHash ? (zh ? "已核对" : "verified") : (zh ? "不匹配" : "mismatch")}</span>
              <span>{preview.dateCoverage.actualStartDate || "—"} — {preview.dateCoverage.actualEndDate || "—"}</span>
              <span>{zh ? "样本外" : "Holdout"} {preview.outOfSampleStartDate || "—"}</span>
              <span>{zh ? "模型" : "Model"} {preview.modelId || "—"}</span>
              <span>{zh ? "预算" : "Budget"} {typeof preview.estimatedTokens === "number" ? preview.estimatedTokens.toLocaleString() : "—"} / {preview.maxTokens.toLocaleString()}</span>
            </div>
            {preview.warnings.map((warning, index) => <p key={index} className={styles.note}>{warning}</p>)}
            {!preview.canStart ? <VStateSurface tone="error" density="compact" title={preview.blockReason || (zh ? "当前数据不满足回测条件" : "Data requirements are not met")} /> : null}
          </VSurface>
        ) : null}
        <p className={styles.note}>{zh ? "策略最多4000字；对照比较按冻结输入逐项核验，不会自动判定哪条更优。" : "Strategy instructions allow up to 4,000 characters. Comparison checks frozen inputs and does not declare a winner."}</p>
        {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
      </div>
    </VDialog>
  );
}
