import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchFinancialClaims, financialEvaluationKeys, revokeFinancialLesson, reviseFinancialLesson } from "../../api/financialEvaluation";
import type { FinancialClaim, FinancialLessonHistory, FinancialLessonState } from "../../api/types/financialEvaluation";
import { fetchFinancialPreferences, financialPreferenceKeys } from "../../api/financialPreferences";
import { VButton, VDialog, VRouteLinkButton, VStateSurface, VSurface, VTextarea } from "../../components/vui";
import styles from "./FinanceLessonManager.styles";

type LessonVersion = Pick<FinancialLessonHistory, "lessonId" | "text" | "state" | "createdAt" | "supersededBy" | "revokedAt">;
type LessonEntry = { claim: FinancialClaim; version: LessonVersion };
type EditorState = { agentId: string; token: number; entry: LessonEntry; mode: "revise" | "revoke" };

function entriesFor(claim: FinancialClaim): LessonEntry[] {
  const versions = [...(claim.lessonHistory ?? [])];
  if (claim.lesson && !versions.some((version) => version.lessonId === claim.lesson!.id) && claim.lessonState !== "absent") {
    versions.push({
      lessonId: claim.lesson.id,
      text: claim.lesson.text,
      state: claim.lessonState ?? "active",
      createdAt: claim.lesson.createdAt,
    });
  }
  return versions.map((version) => ({ claim, version }));
}

function statusLabel(state: FinancialLessonState, zh: boolean) {
  if (state === "active") return zh ? "有效" : "Active";
  if (state === "superseded") return zh ? "已替代" : "Superseded";
  if (state === "revoked") return zh ? "已作废" : "Revoked";
  return zh ? "无有效教训" : "No active lesson";
}

function reportLocation(pathname: string, search: string, claim: FinancialClaim) {
  const params = new URLSearchParams(search);
  params.set("finance_area", "reports");
  params.set("finance_tab", "report");
  params.set("finance_report_collection", "completed");
  params.set("finance_report_session", claim.sessionId);
  params.set("finance_report_turn", claim.turnId);
  return { pathname, search: `?${params.toString()}` };
}

function displaySymbol(symbol: string) {
  const match = /^(sh|sz|bj)(\d{6})$/i.exec(symbol.trim());
  if (!match) return symbol;
  const market = match[1].toLowerCase() === "sh" ? "沪市" : match[1].toLowerCase() === "sz" ? "深市" : "北交所";
  return `${market} ${match[2]}`;
}

export function FinanceLessonManager({ agentId, zh }: { agentId: string; zh: boolean }) {
  const location = useLocation();
  const client = useQueryClient();
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const mounted = useRef(false);
  const activeAgentId = useRef(agentId);
  const editorToken = useRef(0);
  const inFlight = useRef(new Set<string>());
  const requestIds = useRef(new Map<string, string>());
  if (activeAgentId.current !== agentId) {
    activeAgentId.current = agentId;
    editorToken.current += 1;
  }
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; editorToken.current += 1; };
  }, []);
  const claims = useQuery({
    queryKey: financialEvaluationKeys.claims(agentId),
    queryFn: ({ signal }) => fetchFinancialClaims(agentId, signal),
    staleTime: 10_000,
    refetchInterval: 30_000,
    retry: false,
  });
  const preferences = useQuery({
    queryKey: financialPreferenceKeys.agent(agentId),
    queryFn: ({ signal }) => fetchFinancialPreferences(agentId, { signal }),
    staleTime: 15_000,
    retry: false,
  });

  const lessons = (claims.data?.items ?? [])
    .flatMap(entriesFor)
    .sort((left, right) => right.version.createdAt.localeCompare(left.version.createdAt));
  const activeLessonCount = lessons.filter(({ version }) => version.state === "active").length;
  const canRevise = preferences.data?.memoryEnabled === true;
  const selectedEditor = editor?.agentId === agentId ? editor : null;
  const validationListAtLimit = Boolean(claims.data && claims.data.items.length >= claims.data.limit);

  function openEditor(entry: LessonEntry, mode: EditorState["mode"]) {
    const token = ++editorToken.current;
    setError("");
    setDraft(mode === "revise" ? entry.version.text : "");
    setPending(false);
    setEditor({ agentId, token, entry, mode });
  }

  function closeEditor() {
    editorToken.current += 1;
    setEditor(null);
    setError("");
    setPending(false);
  }

  async function submit() {
    const target = selectedEditor;
    if (!target) return;
    const { claim, version } = target.entry;
    const text = draft.trim();
    if (target.mode === "revise" && (!text || !canRevise)) return;
    const fingerprint = target.mode === "revise"
      ? `${target.agentId}:${claim.id}:revise:${version.lessonId}:${text}`
      : `${target.agentId}:${claim.id}:revoke:${version.lessonId}`;
    if (inFlight.current.has(fingerprint)) return;
    inFlight.current.add(fingerprint);
    if (editorToken.current === target.token && activeAgentId.current === target.agentId) {
      setPending(true);
      setError("");
    }
    let clientRequestId = requestIds.current.get(fingerprint);
    if (!clientRequestId) {
      clientRequestId = crypto.randomUUID();
      requestIds.current.set(fingerprint, clientRequestId);
      if (requestIds.current.size > 100) requestIds.current.delete(requestIds.current.keys().next().value!);
    }
    try {
      const result = target.mode === "revise"
        ? await reviseFinancialLesson(target.agentId, claim.id, { text, clientRequestId, expectedLessonId: version.lessonId })
        : await revokeFinancialLesson(target.agentId, claim.id, { clientRequestId, expectedLessonId: version.lessonId });
      if (result.id !== claim.id) throw new Error(zh ? "返回的核验记录与当前记录不匹配" : "The returned claim does not match this record");
      await Promise.all([
        client.invalidateQueries({ queryKey: financialEvaluationKeys.claims(target.agentId) }),
        client.invalidateQueries({ queryKey: ["finance", "reflection-context", target.agentId] }),
      ]);
      if (mounted.current && editorToken.current === target.token && activeAgentId.current === target.agentId) closeEditor();
    } catch (cause) {
      if (mounted.current && editorToken.current === target.token && activeAgentId.current === target.agentId) setError(cause instanceof Error ? cause.message : (zh ? "操作失败，请重试" : "The operation failed. Try again."));
    } finally {
      inFlight.current.delete(fingerprint);
      if (mounted.current && editorToken.current === target.token && activeAgentId.current === target.agentId) setPending(false);
    }
  }

  return <div className={styles.page} data-finance-lesson-manager>
    <div className={styles.row}>
      <div className={styles.headingGroup}>
        <h2 className={styles.title}>{zh ? "股票复盘教训" : "Stock review lessons"}</h2>
        <p className={styles.note}>{zh ? `有效 ${activeLessonCount} 条 · 这里只显示已确认的个人记忆；显示出来不代表本轮研究已经读取。${validationListAtLimit ? ` 核验记录已达到 ${claims.data?.limit} 条上限。` : ""}` : `${activeLessonCount} active · These are confirmed personal memories; their presence does not mean the current research has read them.${validationListAtLimit ? ` The validation list reached its ${claims.data?.limit}-item cap.` : ""}`}</p>
      </div>
      <VButton variant="ghost" isPending={claims.isFetching || preferences.isFetching} onPress={() => { void claims.refetch(); void preferences.refetch(); }}>{zh ? "刷新" : "Refresh"}</VButton>
    </div>
    {preferences.isError ? <VStateSurface tone="error" density="compact" title={zh ? "记忆状态不可用；修订已停用，作废仍可使用" : "Memory status unavailable; revision is disabled, revocation remains available"} /> : preferences.data?.memoryEnabled === false ? <VStateSurface tone="error" density="compact" title={zh ? "个人记忆已关闭；可作废现有教训，重新启用后才能修订" : "Personal memory is disabled; existing lessons can be revoked, and revision requires memory to be enabled"} /> : null}
    {claims.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取股票复盘教训" : "Loading stock review lessons"} /> : claims.isError ? <VStateSurface tone="error" title={zh ? "教训列表不可用" : "Lessons unavailable"} actions={<VButton onPress={() => void claims.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{claims.error.message}</VStateSurface> : lessons.length === 0 ? <VStateSurface tone="empty" title={zh ? "暂无已确认的股票教训" : "No confirmed stock lessons"}>{zh ? "在已核验的报告结论中确认教训后，会在这里显示股票、分析日、版本状态和原报告。" : "Confirm a lesson from a verified report outcome to see its stock, analysis date, version state and source report here."}</VStateSurface> : <div className={styles.lessonList}>
      {lessons.map(({ claim, version }) => <VSurface key={`${claim.id}:${version.lessonId}`} tone="panel" padding="normal" className={styles.panel}>
        <div className={styles.row}>
          <strong className={styles.status}>{displaySymbol(claim.symbol)}</strong>
          <span className={styles.note}>{zh ? "分析日" : "Analysis date"} {claim.analysisDate}</span>
          <span className={styles.status}>{statusLabel(version.state, zh)}</span>
          <span className={styles.note}>{version.createdAt ? new Date(version.createdAt).toLocaleString(zh ? "zh-CN" : "en-US") : ""}</span>
        </div>
        <p className={styles.claim}>{version.text}</p>
        {version.supersededBy ? <p className={styles.note}>{zh ? `替代版本：${version.supersededBy}` : `Replaced by: ${version.supersededBy}`}</p> : null}
        {version.revokedAt ? <p className={styles.note}>{zh ? `${version.state === "superseded" ? "替代时间" : "作废时间"}：${version.revokedAt}` : `${version.state === "superseded" ? "Replaced" : "Revoked"} at: ${version.revokedAt}`}</p> : null}
        <div className={styles.row}>
          {claim.sessionId && claim.turnId ? <VRouteLinkButton variant="secondary" to={reportLocation(location.pathname, location.search, claim)}>{zh ? "打开原报告" : "Open source report"}</VRouteLinkButton> : <VButton variant="secondary" isDisabled>{zh ? "原报告不可用" : "Source report unavailable"}</VButton>}
          {version.state === "active" ? <>
            <VButton variant="ghost" isDisabled={!canRevise || (selectedEditor?.agentId === agentId && pending) || preferences.isPending} onPress={() => openEditor({ claim, version }, "revise")}>{zh ? "修订" : "Revise"}</VButton>
            <VButton variant="ghost" isDisabled={selectedEditor?.agentId === agentId && pending} onPress={() => openEditor({ claim, version }, "revoke")}>{zh ? "作废" : "Revoke"}</VButton>
          </> : null}
        </div>
      </VSurface>)}
    </div>}
    <VDialog
      open={Boolean(selectedEditor)}
      onOpenChange={(open) => { if (!open && !pending) closeEditor(); }}
      title={selectedEditor?.mode === "revoke" ? (zh ? "作废这条股票教训？" : "Revoke this stock lesson?") : (zh ? "修订股票教训" : "Revise stock lesson")}
      footer={selectedEditor ? <div className={styles.row}>
        <VButton variant="secondary" isDisabled={pending} onPress={closeEditor}>{zh ? "取消" : "Cancel"}</VButton>
        <VButton variant="primary" isDisabled={pending || (selectedEditor.mode === "revise" && (!draft.trim() || !canRevise))} isPending={pending} onPress={() => void submit()}>{selectedEditor.mode === "revoke" ? (zh ? "确认作废" : "Confirm revocation") : (zh ? "保存修订" : "Save revision")}</VButton>
      </div> : null}
    >
      {selectedEditor ? <div className={styles.panel}>
        {selectedEditor.mode === "revoke" ? <p className={styles.note}>{zh ? "作废后这条教训将不再参与后续研究，历史版本会保留在这里。原报告和核验记录不会改变。" : "Revoking this lesson removes it from future research and keeps its history here. The source report and outcome check will not change."}</p> : <>
          <p className={styles.note}>{zh ? `正在修订 ${displaySymbol(selectedEditor.entry.claim.symbol)} · 分析日 ${selectedEditor.entry.claim.analysisDate}。旧版本会保留在历史中。` : `Revising ${displaySymbol(selectedEditor.entry.claim.symbol)} · analysis date ${selectedEditor.entry.claim.analysisDate}. The old version stays in history.`}</p>
          <VTextarea aria-label={zh ? "修订后的研究教训" : "Revised stock lesson"} value={draft} maxLength={500} onChange={(event) => setDraft(event.target.value)} />
        </>}
        {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
      </div> : null}
    </VDialog>
  </div>;
}
