import styles from "./WorkflowArtifactDialog.styles";
import { useQuery } from "@tanstack/react-query";
import { VButton, VDialog, VRouteLinkButton } from "../../../components/vui";
import { listTeamFlowArtifacts, teamFlowKeys } from "../../../api/genericTeamWorkflows";
import type { Run } from "./workflowModel";
export function WorkflowArtifactDialog({ teamId, run, open, onOpenChange }: {
    teamId: string;
    run?: Run;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}) {
    const artifacts = useQuery({
        queryKey: teamFlowKeys.artifacts(teamId, run?.id || ""),
        queryFn: ({ signal }) => listTeamFlowArtifacts(teamId, run!.id, signal),
        enabled: Boolean(open && run),
    });
    return <VDialog open={open} onOpenChange={onOpenChange} title={run ? `${run.flow.name} · ${run.status === "waiting" ? "已有产物" : "交付结果"}` : "交付结果"} description="来自本次运行的原生会话。" size="lg" className={styles.control1} footer={<VButton onClick={() => onOpenChange(false)}>返回工作台</VButton>}>
    {artifacts.isPending ? <p role="status" className={styles.text1}>正在读取产物…</p>
            : artifacts.isError ? <div role="alert" className={styles.text2}>{artifacts.error.message}<VButton onClick={() => void artifacts.refetch()}>重新读取</VButton></div>
                : !artifacts.data.artifacts.length ? <p className={styles.text3}>本次运行还没有可读产物。</p>
                    : <div className={styles.grid1}>{artifacts.data.artifacts.map(artifact => <article key={`${artifact.nodeId}:${artifact.turnId}`} className={styles.grid2}>
            <div className={styles.row1}><h2 className={styles.heading1}>{artifact.label}</h2>
              {artifact.chatUrl?.startsWith("/chat?") && <VRouteLinkButton to={artifact.chatUrl} variant="ghost">打开原生会话</VRouteLinkButton>}</div>
            <div className={styles.text4}>{artifact.content || "本步骤没有文本输出。"}</div>
          </article>)}</div>}
  </VDialog>;
}
