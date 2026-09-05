import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { listProjectAgentBusTimeline, PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT, projectAgentBusEventsForTeam } from "../../api/projectAgentBus";
import { queryKeys } from "../../api/queryKeys";

export function useTeamCommunicationEvents(teamId: string, visible: boolean) {
  const projectBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: ({ signal }) => listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT, { signal }),
    enabled: Boolean(teamId) && visible,
  });
  const teamBusEvents = useMemo(
    () => projectAgentBusEventsForTeam(projectBusQuery.data, teamId),
    [projectBusQuery.data, teamId],
  );
  return { projectBusQuery, teamBusEvents };
}
