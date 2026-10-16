/** @vitest-environment happy-dom */
import React, {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach,beforeEach,describe,it,expect,vi} from "vitest";
import type {Team,ChatRoomDetail} from "../../api/types";
import {useTeamMemberSessionRecovery} from "./useTeamMemberSessionRecovery";
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
const team={teamId:"t",linkedChatRoomId:"r",members:[{memberId:"m",agentId:"new-agent",agentStatus:"active"}]} as Team;
const room={roomId:"r",participants:[{kind:"agent",agentId:"new-agent",sessionId:"new-session"}]} as ChatRoomDetail;
describe("member action session recovery",()=>{
 let host:HTMLDivElement,root:Root,recover:(team:Team,memberId:string)=>void;
 let props:Parameters<typeof useTeamMemberSessionRecovery>[0];
 function Probe(){recover=useTeamMemberSessionRecovery(props);return null;}
 function render(patch:Partial<typeof props>={}){props={...props,...patch};act(()=>root.render(<Probe/>));}
 beforeEach(()=>{host=document.createElement("div");document.body.append(host);root=createRoot(host);props={team,room,roomDataUpdatedAt:10,searchParams:new URLSearchParams("teamConversationTeamId=t&teamConversation=member&teamMember=m&session=old&teamView=discussion"),replaceSearch:vi.fn()};});
 afterEach(()=>{act(()=>root.unmount());host.remove();});
 it("does not repair arbitrary URLs without a successful member action",()=>{render();render({roomDataUpdatedAt:11});expect(props.replaceSearch).not.toHaveBeenCalled();});
 it("waits for the new Agent's refreshed room session and repairs only the selected conversation",()=>{
  render({room:{...room,participants:[{kind:"agent",agentId:"old-agent",sessionId:"old"}]} as ChatRoomDetail});
  act(()=>recover(team,"m"));expect(props.replaceSearch).not.toHaveBeenCalled();
  render({room,roomDataUpdatedAt:10});expect(props.replaceSearch).not.toHaveBeenCalled();
  render({roomDataUpdatedAt:11});expect(props.replaceSearch).toHaveBeenCalledOnce();
  const next=vi.mocked(props.replaceSearch).mock.calls[0][0];expect(next.get("session")).toBe("new-session");expect(next.get("teamMember")).toBe("m");expect(next.get("teamView")).toBe("discussion");expect(next.has("room")).toBe(false);
 });
 it("does not navigate after the user changes people",()=>{render();act(()=>recover(team,"m"));render({roomDataUpdatedAt:11,searchParams:new URLSearchParams("teamConversationTeamId=t&teamConversation=member&teamMember=another")});expect(props.replaceSearch).not.toHaveBeenCalled();});
 it("rejects a room from a different team during refresh",()=>{render();act(()=>recover(team,"m"));render({roomDataUpdatedAt:11,room:{...room,roomId:"another-room"}});expect(props.replaceSearch).not.toHaveBeenCalled();render({room});expect(props.replaceSearch).toHaveBeenCalledOnce();});
});
