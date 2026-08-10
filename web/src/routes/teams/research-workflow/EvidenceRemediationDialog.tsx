import { type Key, useEffect, useMemo, useState } from "react";

import type { NodeCommandCapability } from "../../../api/types/researchWorkflow";
import {
  VButton,
  VCheckbox,
  VDialog,
  VFieldRow,
  VInput,
  VSelect,
  VTextarea,
} from "../../../components/vui";
import styles from "./EvidenceRemediationDialog.styles";

type ResolutionKind = "add_budget" | "reduce_scope";

function candidateIdsFrom(capability: NodeCommandCapability | null): string[] {
  const raw = capability?.payload?.evidenceGapCandidateIds;
  return Array.isArray(raw)
    ? [...new Set(raw.map((item) => String(item).trim()).filter(Boolean))].sort()
    : [];
}

export function EvidenceRemediationDialog(props: {
  open: boolean;
  capability: NodeCommandCapability | null;
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const candidateIds = useMemo(
    () => candidateIdsFrom(props.capability),
    [props.capability],
  );
  const [resolutionKind, setResolutionKind] = useState<ResolutionKind>("add_budget");
  const [scopeCandidateIds, setScopeCandidateIds] = useState<string[]>(candidateIds);
  const [operatorReason, setOperatorReason] = useState("");
  const [tokens, setTokens] = useState("0");
  const [toolCalls, setToolCalls] = useState("0");
  const [wallClockSeconds, setWallClockSeconds] = useState("0");
  const [computeUnits, setComputeUnits] = useState("0");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  useEffect(() => {
    if (!props.open) return;
    setResolutionKind("add_budget");
    setScopeCandidateIds(candidateIds);
    setOperatorReason("");
    setTokens("0");
    setToolCalls("0");
    setWallClockSeconds("0");
    setComputeUnits("0");
    setSubmitting(false);
    setSubmitError("");
  }, [candidateIds, props.open]);

  const additionalBudget = {
    tokens: Math.max(0, Number.parseInt(tokens || "0", 10) || 0),
    toolCalls: Math.max(0, Number.parseInt(toolCalls || "0", 10) || 0),
    wallClockSeconds: Math.max(0, Number.parseInt(wallClockSeconds || "0", 10) || 0),
    computeUnits: Math.max(0, Number.parseInt(computeUnits || "0", 10) || 0),
  };
  const budgetIncrement = Object.values(additionalBudget).reduce((sum, value) => sum + value, 0);
  const error = !candidateIds.length
    ? "缺少后端固化的证据缺口候选"
    : !operatorReason.trim()
      ? "请填写本次补救原因"
      : resolutionKind === "add_budget" && budgetIncrement <= 0
        ? "追加预算至少有一项大于 0"
        : resolutionKind === "reduce_scope" && (
            scopeCandidateIds.length === 0 || scopeCandidateIds.length >= candidateIds.length
          )
          ? "缩小范围必须保留至少一个候选，且少于原缺口范围"
          : "";

  const setKind = (key: Key | null) => {
    const next = key === "reduce_scope" ? "reduce_scope" : "add_budget";
    setResolutionKind(next);
    if (next === "add_budget") setScopeCandidateIds(candidateIds);
  };
  const toggleCandidate = (candidateId: string, selected: boolean) => {
    setScopeCandidateIds((current) => (
      selected
        ? [...new Set([...current, candidateId])].sort()
        : current.filter((item) => item !== candidateId)
    ));
  };
  const submit = async () => {
    if (error) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      await props.onSubmit({
        evidenceGapCandidateIds: candidateIds,
        scopeCandidateIds,
        resolutionKind,
        additionalBudget: resolutionKind === "add_budget" ? additionalBudget : {},
        operatorReason: operatorReason.trim(),
      });
      props.onOpenChange(false);
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <VDialog
      open={props.open}
      onOpenChange={props.onOpenChange}
      title="创建证据补救运行"
      size="md"
      footer={(
        <>
          <VButton type="button" variant="secondary" onPress={() => props.onOpenChange(false)}>
            取消
          </VButton>
          <VButton type="button" variant="primary" isDisabled={props.busy || submitting || Boolean(error)} onPress={() => void submit()}>
            创建子运行
          </VButton>
        </>
      )}
    >
      <div className={styles.form} data-vui="evidence-remediation-form">
        <VFieldRow label="补救方式">
          <VSelect
            selectedKey={resolutionKind}
            onSelectionChange={setKind}
            options={[
              { id: "add_budget", label: "追加预算" },
              { id: "reduce_scope", label: "缩小范围", disabled: candidateIds.length < 2 },
            ]}
          />
        </VFieldRow>
        <VFieldRow label="候选范围">
          <div className={styles.scopeList}>
            {candidateIds.map((candidateId) => (
              <VCheckbox
                key={candidateId}
                isSelected={scopeCandidateIds.includes(candidateId)}
                isDisabled={resolutionKind === "add_budget"}
                onChange={(selected) => toggleCandidate(candidateId, selected)}
              >
                <span className={styles.candidate}>{candidateId}</span>
              </VCheckbox>
            ))}
          </div>
        </VFieldRow>
        {resolutionKind === "add_budget" ? (
          <div className={styles.budgetGrid}>
            <VFieldRow label="Token">
              <VInput type="number" min={0} value={tokens} onChange={(event) => setTokens(event.target.value)} />
            </VFieldRow>
            <VFieldRow label="工具调用">
              <VInput type="number" min={0} value={toolCalls} onChange={(event) => setToolCalls(event.target.value)} />
            </VFieldRow>
            <VFieldRow label="运行秒数">
              <VInput type="number" min={0} value={wallClockSeconds} onChange={(event) => setWallClockSeconds(event.target.value)} />
            </VFieldRow>
            <VFieldRow label="计算单元">
              <VInput type="number" min={0} value={computeUnits} onChange={(event) => setComputeUnits(event.target.value)} />
            </VFieldRow>
          </div>
        ) : null}
        <VFieldRow label="补救原因">
          <VTextarea minRows={3} value={operatorReason} onChange={(event) => setOperatorReason(event.target.value)} />
        </VFieldRow>
        {error || submitError ? <p className={styles.error} role="status">{error || submitError}</p> : null}
      </div>
    </VDialog>
  );
}
