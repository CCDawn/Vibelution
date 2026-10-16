import { useEffect, useState } from "react";
import type { ChatRoomDetail, Team } from "../../api/types";
import { teamMemberSessionId } from "./TeamConversationRail";

/** Only a successful member action may repair the URL after a fresh room read. */
export function useTeamMemberSessionRecovery({ team, room, roomDataUpdatedAt, searchParams, replaceSearch }: {
  team: Team | null; room: ChatRoomDetail | null; roomDataUpdatedAt: number;
  searchParams: URLSearchParams; replaceSearch: (next: URLSearchParams) => void;
}) {
  const [request, setRequest] = useState<{teamId:string;memberId:string;agentId:string;after:number} | null>(null);
  useEffect(() => {
    if (!request) return;
    if (searchParams.get("teamConversationTeamId") !== request.teamId
      || searchParams.get("teamConversation") !== "member" || searchParams.get("teamMember") !== request.memberId) {
      setRequest(null); return;
    }
    const member = team?.teamId === request.teamId ? team.members.find(item => item.memberId === request.memberId) : undefined;
    if (!member || member.agentId !== request.agentId || member.agentStatus === "stale" || roomDataUpdatedAt <= request.after) return;
    const expectedRoomId = team?.linkedChatRoomId || team?.linkedChatRoom?.roomId;
    if (expectedRoomId && room?.roomId !== expectedRoomId) return;
    const sessionId = teamMemberSessionId(member, room);
    if (!sessionId) return;
    const next = new URLSearchParams(searchParams);
    next.set("session", sessionId); next.delete("room");
    replaceSearch(next); setRequest(null);
  }, [request, team, room, roomDataUpdatedAt, searchParams, replaceSearch]);
  return (savedTeam: Team, memberId: string) => {
    const member = savedTeam.members.find(item => item.memberId === memberId);
    if (member) setRequest({teamId:savedTeam.teamId,memberId,agentId:member.agentId,after:roomDataUpdatedAt});
  };
}
