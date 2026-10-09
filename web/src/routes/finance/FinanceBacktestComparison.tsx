import { useEffect, useRef, useState } from "react";
import { Download, GitCompareArrows } from "lucide-react";
import { compareAIBacktests, downloadAIBacktestComparison } from "../../api/financialBacktests";
import type {
  AIBacktestComparisonAxis,
  AIBacktestComparisonResult,
  AIBacktestComparisonRow,
  AIBacktestSummary,
} from "../../api/types/financialBacktests";
import { VButton, VCheckbox, VChip, VDenseTable, VSelect, VStateSurface, VSurface } from "../../components/vui";
import styles from "./FinanceAIBacktest.styles";

type Props = {
  agentId: string;
  runs: AIBacktestSummary[];
  zh: boolean;
};

const comparisonStatuses = {
  comparable: { zh: "可比", en: "Comparable" },
  incomplete: { zh: "未完成", en: "Incomplete" },
  incompatible: { zh: "不可比较", en: "Incompatible" },
} as const;

const runStatuses: Record<AIBacktestSummary["status"], { zh: string; en: string }> = {
  queued: { zh: "排队中", en: "Queued" },
  running: { zh: "运行中", en: "Running" },
  stop_requested: { zh: "正在停止", en: "Stopping" },
  stopped: { zh: "已停止", en: "Stopped" },
  blocked: { zh: "条件不满足", en: "Blocked" },
  paused_unknown: { zh: "调用结果待确认", en: "Uncertain call" },
  failed: { zh: "失败", en: "Failed" },
  completed: { zh: "已完成", en: "Completed" },
};

function symbolsForRun(run: Pick<AIBacktestSummary, "symbol" | "symbols">) {
  return run.symbols?.length ? run.symbols : run.symbol ? [run.symbol] : [];
}

function assetLabel(run: AIBacktestSummary, zh: boolean) {
  const symbols = symbolsForRun(run);
  if (symbols.length > 1) return (zh ? "组合" : "Basket") + " · " + symbols.length + (zh ? " 只" : " stocks") + " · " + symbols.slice(0, 3).join(" / ");
  return symbols[0] || (zh ? "未知标的" : "Unknown asset");
}

function pct(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) + "%" : "—";
}

function statusLabel(status: string, zh: boolean) {
  return comparisonStatuses[status as keyof typeof comparisonStatuses]?.[zh ? "zh" : "en"] ?? status;
}

function summary(run: AIBacktestSummary, zh: boolean) {
  const when = new Date(run.startedAt || run.updatedAt).toLocaleString(zh ? "zh-CN" : "en-US");
  return runStatuses[run.status][zh ? "zh" : "en"] + " · " + assetLabel(run, zh) + " · " + when + " · " + run.completedDecisionCount + "/" + run.decisionCount;
}

function metricsFor(row: AIBacktestComparisonRow) {
  return row.evaluation?.outOfSample.metrics ?? row.metrics;
}

function hashLabel(value: string | null, zh: boolean) {
  return value ? <span title={value}>{zh ? "已核验" : "Verified"} · {value.slice(0, 12)}</span> : "—";
}

export function FinanceBacktestComparison({ agentId, runs, zh }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [axis, setAxis] = useState<AIBacktestComparisonAxis>("strategy");
  const [result, setResult] = useState<AIBacktestComparisonResult | null>(null);
  const [pending, setPending] = useState<"compare" | "download" | "">("");
  const [error, setError] = useState("");
  const gate = useRef(false);
  const operation = useRef<symbol | null>(null);
  const generation = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
    };
  }, []);

  useEffect(() => {
    generation.current += 1;
    operation.current = null;
    gate.current = false;
    setPending("");
    setSelectedIds([]);
    setResult(null);
    setError("");
  }, [agentId]);

  function changeSelection(runId: string, checked: boolean) {
    generation.current += 1;
    setSelectedIds((current) => {
      if (checked) return current.length >= 4 || current.includes(runId) ? current : [...current, runId];
      return current.filter((item) => item !== runId);
    });
    setResult(null);
    setError("");
  }

  function changeAxis(value: AIBacktestComparisonAxis) {
    generation.current += 1;
    setAxis(value);
    setResult(null);
    setError("");
  }

  async function perform(kind: "compare" | "download", work: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true;
    const owner = Symbol(kind);
    operation.current = owner;
    const requestGeneration = generation.current;
    setPending(kind);
    setError("");
    try {
      await work();
    } catch (cause) {
      if (mounted.current && generation.current === requestGeneration && operation.current === owner) {
        setError(cause instanceof Error ? cause.message : "操作失败，请重试");
      }
    } finally {
      if (operation.current === owner) {
        operation.current = null;
        gate.current = false;
        if (mounted.current) setPending("");
      }
    }
  }

  const runById = new Map(runs.map((run) => [run.runId, run]));
  const visibleSelected = selectedIds.filter((runId) => runById.has(runId));
  const validSelection = visibleSelected.length >= 2 && visibleSelected.length <= 4;

  return (
    <div className={styles.comparisonShell}>
      <VButton
        variant="secondary"
        icon={<GitCompareArrows size={14} aria-hidden="true" />}
        isDisabled={runs.length < 2}
        onPress={() => setExpanded((value) => !value)}
      >
        {expanded ? (zh ? "收起历史对照" : "Hide comparison") : (zh ? "对照历史结果" : "Compare history")}
      </VButton>
      {expanded ? (
        <VSurface tone="panel" padding="compact" className={styles.panel}>
          <div className={styles.row}>
            <strong>{zh ? "历史结果对照" : "Historical comparison"}</strong>
            <span className={styles.note}>{zh ? "选择 2–4 条；服务端核对冻结数据与共同参数。" : "Choose 2–4 runs; the server verifies frozen data and shared assumptions."}</span>
            <label className={styles.field}>
              {zh ? "比较维度" : "Compare by"}
              <VSelect
                aria-label={zh ? "回测比较维度" : "Backtest comparison axis"}
                isDisabled={pending !== ""}
                selectedKey={axis}
                options={[
                  { id: "strategy", label: zh ? "策略" : "Strategy" },
                  { id: "model", label: zh ? "模型" : "Model" },
                ]}
                onSelectionChange={(key) => changeAxis(String(key ?? "strategy") as AIBacktestComparisonAxis)}
              />
            </label>
            <VButton
              variant="primary"
              icon={<GitCompareArrows size={14} aria-hidden="true" />}
              isPending={pending === "compare"}
              isDisabled={pending !== "" || !validSelection}
              onPress={() => void perform("compare", async () => {
                const requestGeneration = generation.current;
                const response = await compareAIBacktests(agentId, { runIds: visibleSelected, axis });
                if (!mounted.current || generation.current !== requestGeneration) return;
                const actualIds = response.rows.map((row) => row.runId);
                if (response.axis !== axis || actualIds.length !== visibleSelected.length || actualIds.some((id, index) => id !== visibleSelected[index])) {
                  throw new Error(zh ? "比较响应与所选回测不匹配" : "Comparison response does not match selected runs");
                }
                setResult(response);
              })}
            >
              {zh ? "生成比较" : "Compare"}
            </VButton>
          </div>
          <div className={styles.comparisonSelection}>
            {runs.map((run) => {
              const checked = visibleSelected.includes(run.runId);
              return (
                <VCheckbox
                  key={run.runId}
                  aria-label={(zh ? "选择回测 " : "Select backtest ") + run.runId}
                  isSelected={checked}
                  isDisabled={pending !== "" || (!checked && visibleSelected.length >= 4)}
                  onChange={(next) => changeSelection(run.runId, next)}
                >
                  <span title={summary(run, zh)}>{assetLabel(run, zh)} · {runStatuses[run.status][zh ? "zh" : "en"]} · {run.runId.slice(0, 12)}</span>
                </VCheckbox>
              );
            })}
          </div>
          {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
          {result ? (
            <div className={styles.comparisonResult}>
              <div className={styles.row}>
                <VChip tone={result.status === "comparable" ? "success" : result.status === "incomplete" ? "warning" : "danger"}>
                  {statusLabel(result.status, zh)}
                </VChip>
                <span>{zh ? "数据" : "Data"} {hashLabel(result.dataHash, zh)}</span>
                <span>{zh ? "共同参数" : "Shared inputs"} {hashLabel(result.commonParamsHash, zh)}</span>
                <span>{zh ? "样本外起点" : "Holdout"} {result.outOfSampleStartDate || "—"}</span>
                <VButton
                  variant="ghost"
                  icon={<Download size={14} aria-hidden="true" />}
                  isPending={pending === "download"}
                  isDisabled={pending !== ""}
                  onPress={() => void perform("download", async () => downloadAIBacktestComparison(result))}
                >
                  {zh ? "下载 JSON" : "Download JSON"}
                </VButton>
              </div>
              {result.status === "comparable" ? (
                <>
                  <div className={styles.table}>
                    <VDenseTable
                      resizable
                      className={styles.comparisonTable}
                      ariaLabel={zh ? "可比回测指标" : "Comparable backtest metrics"}
                      rows={result.rows}
                      getRowKey={(row) => row.runId}
                      emptyText={zh ? "没有可比较结果" : "No comparable runs"}
                      columns={[
                        { id: "run", width: 115, header: zh ? "回测" : "Run", render: (row) => <span title={row.runId}>{row.runId.slice(0, 12)}</span> },
                        { id: "model", width: 160, header: zh ? "模型" : "Model", render: (row) => row.modelId ? <span title={row.modelId}>{row.modelId.split("/").at(-1)}</span> : "—" },
                        { id: "strategy", width: 200, header: zh ? "策略" : "Strategy", render: (row) => row.strategy ? <span title={row.strategy}>{row.strategy}</span> : "—" },
                        { id: "return", header: zh ? "全区间收益" : "Total return", render: (row) => pct(row.metrics?.totalReturnPct) },
                        { id: "oos-return", header: zh ? "样本外收益" : "Holdout return", render: (row) => pct(metricsFor(row)?.totalReturnPct) },
                        { id: "oos-excess", header: zh ? "样本外超额" : "Holdout excess", render: (row) => pct(metricsFor(row)?.excessReturnPct) },
                        { id: "oos-drawdown", header: zh ? "样本外回撤" : "Holdout drawdown", render: (row) => pct(metricsFor(row)?.maxDrawdownPct) },
                        { id: "fills", header: zh ? "成交 / 费用" : "Fills / fees", render: (row) => row.metrics ? (row.metrics.tradeCount ?? "—") + " / " + (typeof row.metrics.fees === "number" ? row.metrics.fees.toFixed(2) : "—") : "—" },
                      ]}
                    />
                  </div>
                  <p className={styles.note}>{result.notice}</p>
                </>
              ) : (
                <div className={styles.comparisonReasons}>
                  {result.reasons.map((reason, index) => (
                    <VStateSurface key={reason.code + ":" + index} tone="info" density="compact" title={reason.message} />
                  ))}
                  <p className={styles.note}>{result.notice}</p>
                </div>
              )}
            </div>
          ) : null}
        </VSurface>
      ) : null}
    </div>
  );
}
