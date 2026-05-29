import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "./AppShell";
import { AgentsRoute } from "../routes/AgentsRoute";
import { ChatCodingRoute } from "../routes/ChatCodingRoute";
import { ConfigRoute } from "../routes/ConfigRoute";
import { EvolutionRoute } from "../routes/EvolutionRoute";
import { GitRoute } from "../routes/GitRoute";
import { LegacyChatRoomsRedirect } from "../routes/LegacyChatRoomsRedirect";
import { HomeRedirect } from "../routes/HomeRedirect";
import { LegacyEvolutionRedirect } from "../routes/LegacyEvolutionRedirect";
import { LogsRoute } from "../routes/LogsRoute";
import { MemoryRoute } from "../routes/MemoryRoute";
import { PetRoute } from "../routes/PetRoute";
import { PromptTemplatesRoute } from "../routes/PromptTemplatesRoute";
import { ResetRoute } from "../routes/ResetRoute";
import { ResearchFlowCanvasRoute } from "../routes/ResearchFlowCanvasRoute";
import { ResearchRoute } from "../routes/ResearchRoute";
import { SkillsRoute } from "../routes/SkillsRoute";
import { SupervisedReviewRoute } from "../routes/SupervisedReviewRoute";
import { TeamsRoute } from "../routes/TeamsRoute";
import { ToolsRoute } from "../routes/ToolsRoute";
import { WorkbenchDomainRoute } from "../routes/WorkbenchDomainRoute";
import { WorkbenchModeRoute } from "../routes/WorkbenchModeRoute";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <HomeRedirect /> },
      {
        path: "chat",
        element: (
          <WorkbenchDomainRoute domain="chat">
            <ChatCodingRoute />
          </WorkbenchDomainRoute>
        ),
      },
      {
        path: "chat-rooms",
        element: <LegacyChatRoomsRedirect />,
      },
      {
        path: "supervised-evolution",
        element: (
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="live" />
          </WorkbenchModeRoute>
        ),
      },
      {
        path: "supervised-evolution/runs",
        element: (
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="runs" />
          </WorkbenchModeRoute>
        ),
      },
      {
        path: "supervised-evolution/library",
        element: (
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="library" />
          </WorkbenchModeRoute>
        ),
      },
      {
        path: "supervised-evolution/review",
        element: (
          <WorkbenchModeRoute mode="supervised_evolution">
            <SupervisedReviewRoute />
          </WorkbenchModeRoute>
        ),
      },
      {
        path: "self-evolution",
        element: (
          <WorkbenchModeRoute mode="self_evolution">
            <EvolutionRoute forcedTrack="self" />
          </WorkbenchModeRoute>
        ),
      },
      { path: "evolution", element: <LegacyEvolutionRedirect /> },
      { path: "agents", element: <AgentsRoute /> },
      { path: "agents/teams", element: <TeamsRoute /> },
      { path: "agents/prompts", element: <PromptTemplatesRoute /> },
      { path: "agents/tools", element: <ToolsRoute /> },
      { path: "agents/skills", element: <SkillsRoute /> },
      { path: "agents/memory", element: <MemoryRoute forcedView="overview" /> },
      { path: "agents/memory/effective", element: <MemoryRoute forcedView="effective" /> },
      { path: "agents/memory/manage", element: <MemoryRoute forcedView="manage" /> },
      { path: "agents/memory/sources", element: <MemoryRoute forcedView="sources" /> },
      { path: "git", element: <GitRoute /> },
      { path: "logs", element: <LogsRoute /> },
      { path: "research", element: <ResearchRoute /> },
      { path: "research/flow-canvas", element: <ResearchFlowCanvasRoute /> },
      { path: "pet", element: <PetRoute /> },
      { path: "reset", element: <ResetRoute /> },
      { path: "config", element: <ConfigRoute /> },
    ],
  },
]);
