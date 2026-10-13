import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { fetchRuntimeSummary } from "../../api/runtime";
import { queryKeys } from "../../api/queryKeys";
import { deriveActiveWorkIndicator } from "../../app/systemStatus";
import { markProjectNoticesSeen, type ProjectUtilityKind } from "../../app/projectUtilityRail";
import { RuntimeTasksPanel } from "../auxConversations/RuntimeTasksPanel";
import { ProjectNotificationsPanel } from "./ProjectNotificationsPanel";
import { ProjectGitPanel } from "./ProjectGitPanel";
import { useChatRouteSelection } from "./useChatRouteSelection";

export function ProjectUtilityPanel({ kind, lang, sessionId, onOpenSession }: { kind: ProjectUtilityKind; lang: "zh" | "en"; sessionId?: string; onOpenSession?: (id: string) => void }) {
  const navigate = useNavigate();
  const chatRoute = useChatRouteSelection();
  const runtime = useQuery({ queryKey: queryKeys.runtimeSummary(), queryFn: ({ signal }) => fetchRuntimeSummary({ signal }), enabled: kind === "project_tasks", staleTime: 10_000 });
  if (kind === "project_git") return <ProjectGitPanel lang={lang} />;
  if (kind === "project_notices") return <ProjectNotificationsPanel lang={lang} onOpenSession={onOpenSession} onSeen={markProjectNoticesSeen} onExpand={() => chatRoute.openProjectBus({ telemetrySource: "project_notifications_expand" })} />;
  return <RuntimeTasksPanel lang={lang} activeSessionId={sessionId} activeWork={deriveActiveWorkIndicator(runtime.data, lang)} onOpenSession={onOpenSession} onExpand={(taskId) => navigate(taskId ? `/aux?taskId=${encodeURIComponent(taskId)}` : "/aux")} />;
}
