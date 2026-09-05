import { useQuery } from "@tanstack/react-query";
import { fetchResearchWorkflowHandoffDetail } from "../../../api/research-workflow/domain-projections";
import { queryKeys } from "../../../api/queryKeys";
import { VButton, VRouteLinkButton, VSurface } from "../../../components/vui";
import styles from "./KnowledgePackageReader.styles";
import { safeSourceUrl } from "./evidenceReadingModel";

export function KnowledgePackageReader({ runId, teamId, handoffId, lang = "zh" }: {
  runId: string; teamId: string; handoffId: string; lang?: "zh" | "en";
}) {
  const zh = lang === "zh";
  const reading = useQuery({
    queryKey: queryKeys.researchWorkflowHandoffDetail(runId, teamId, handoffId),
    queryFn: () => fetchResearchWorkflowHandoffDetail(runId, handoffId, { teamId }),
  });
  if (reading.isPending) return <p role="status">{zh ? "正在读取知识包正文…" : "Loading knowledge package…"}</p>;
  if (reading.isError) return <div role="alert">
    <p>{zh ? "正文读取失败，交接状态未改变。" : "Reading failed. Handoff status is unchanged."}</p>
    <VButton variant="secondary" onClick={() => void reading.refetch()}>{zh ? "重试读取" : "Retry reading"}</VButton>
  </div>;
  const packages = reading.data.knowledgePackages;
  if (!packages.length) return <p>{zh ? "此交接未记录可阅读的知识包草稿。" : "No knowledge draft is recorded for this handoff."}</p>;
  return <div className={styles.root}>
    {packages.map((item) => {
      const sourceUrl = safeSourceUrl(item.sourceUrl);
      return <VSurface key={item.artifactId} tone="panel" className={styles.package}>
        {item.status === "unavailable" ? <p role="status">{zh ? "无法核验此交接对应的正文，请检查产物引用。" : "This handoff's content could not be verified. Check its artifact reference."}</p> : <>
          <h5 className={styles.heading}>{item.title || (zh ? "未命名知识包草稿" : "Untitled knowledge draft")}</h5>
          <p className={styles.note}>{zh ? "知识包草稿 · 阅读内容不代表已审核或已入库" : "Knowledge draft · Reading does not imply approval or publication"}</p>
          {item.summary ? <section><h6 className={styles.heading}>{zh ? "摘要" : "Summary"}</h6><p className={styles.body}>{item.summary}</p></section> : null}
          <section><h6 className={styles.heading}>{zh ? "正文" : "Content"}</h6><p className={styles.body}>{item.content || (zh ? "产物中未记录正文。" : "No body text was recorded.")}</p></section>
          {item.riskSummary || item.uncertainties.length ? <section><h6 className={styles.heading}>{zh ? "风险与待核查事项" : "Risks and open questions"}</h6><p>{item.riskSummary}</p><ul className={styles.list}>{item.uncertainties.map((text, i) => <li key={i}>{text}</li>)}</ul></section> : null}
          {sourceUrl ? <VRouteLinkButton to={sourceUrl} target="_blank" rel="noopener noreferrer" variant="secondary">{zh ? "打开原始来源 ↗" : "Open original source ↗"}</VRouteLinkButton> : <p>{zh ? "产物未记录可打开的网页来源。" : "No web source is recorded."}</p>}
        </>}
      </VSurface>;
    })}
  </div>;
}
