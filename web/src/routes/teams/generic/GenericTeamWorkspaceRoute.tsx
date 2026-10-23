import styles from "./GenericTeamWorkspaceRoute.styles";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchTeam } from "../../../api/teams";
import { queryKeys } from "../../../api/queryKeys";
import { VButton } from "../../../components/vui";
import { usePageVisibility } from "../../../app/pollingPolicy";
import { useTeamsCatalogQueries } from "../useTeamsCatalogQueries";
import { isChallengeCupResearchWorkflowTeam } from "../teamKindModel";
import { GenericWorkflowWorkspace } from "./GenericWorkflowWorkspace";
import { WorkflowWorkspaceLoading } from "./WorkflowWorkspaceLoading";
import { workflowTeamParams } from "./workspaceRouteModel";
export function GenericTeamWorkspaceRoute({ forcedTeamId, legacy }: {
    forcedTeamId?: string;
    legacy: ReactNode;
}) {
    const [params, setParams] = useSearchParams();
    const catalog = useTeamsCatalogQueries({
        pageVisible: usePageVisibility(), requestedTeamId: forcedTeamId || params.get("team") || params.get("teamId") || "", requestedAgentId: params.get("agent") || "",
    });
    const teamId = forcedTeamId || catalog.requestedVisibleTeamId || catalog.requestedVisibleAgentTeamId || catalog.fallbackVisibleTeamId;
    const detail = useQuery({ queryKey: queryKeys.team(teamId, "full"), queryFn: ({ signal }) => fetchTeam(teamId, { signal, detail: "full" }), enabled: Boolean(teamId), staleTime: 10000 });
    const team = detail.data;
    if (catalog.teamsQuery.isError || detail.isError)
        return <div role="alert" className={styles.grid1}><p>{catalog.teamsQuery.error?.message || detail.error?.message}</p><VButton onClick={() => { void catalog.teamsQuery.refetch(); void detail.refetch(); }}>重新读取团队</VButton></div>;
    if (catalog.teamsQuery.isPending || detail.isPending && teamId)
        return <WorkflowWorkspaceLoading teamId={teamId || forcedTeamId || params.get("team") || params.get("teamId") || ""} teams={catalog.visibleTeams.map(item => ({ id: item.teamId, label: item.name }))}/>;
    if (!team)
        return legacy;
    // Ordinary team homes retain their native discussion/task entry. The flow selector
    // can explicitly open this same designer for any team without changing that default.
    if (!isChallengeCupResearchWorkflowTeam(team) && params.get("teamWorkspace") !== "flows")
        return legacy;
    const workspaceTeam = { ...team, members: team.members.map(member => {
        const agent = catalog.activeAgentsById.get(member.agentId);
        return { ...member, agentName: member.agentName || agent?.displayName || "", agentCode: member.agentCode || agent?.agentCode || "" };
    }) };
    const goToTeamView = (history: boolean) => {
        const next = workflowTeamParams(params, teamId);
        next.delete("teamWorkspace");
        if (history) {
            next.set("workflowWorkspace", "legacy");
            next.set("researchView", "workflow");
        }
        else {
            next.set("teamView", "discussion");
            next.set("researchView", "discussion");
        }
        setParams(next);
    };
    return <GenericWorkflowWorkspace key={teamId} team={workspaceTeam} teams={catalog.visibleTeams.map(item => ({ id: item.teamId, label: item.name }))} onTeam={id => setParams(workflowTeamParams(params, id))} onDiscussion={() => goToTeamView(false)} onHistory={() => goToTeamView(true)}/>;
}
