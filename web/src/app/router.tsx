import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "./AppShell";
import { LauncherShell } from "./LauncherShell";
import { RouteErrorBoundary, type RouteErrorSurface } from "./RouteErrorBoundary";
import { LegacyChatRoomsRedirect } from "../routes/LegacyChatRoomsRedirect";
import { LegacyTeamsRedirect } from "../routes/LegacyTeamsRedirect";
import { LegacyMemoryRedirect } from "../routes/LegacyMemoryRedirect";
import { HomeRedirect } from "../routes/HomeRedirect";
import { LegacyEvolutionRedirect } from "../routes/LegacyEvolutionRedirect";
import { WorkbenchDomainRoute } from "../routes/WorkbenchDomainRoute";
import { WorkbenchModeRoute } from "../routes/WorkbenchModeRoute";
import { postBrowserTelemetry } from "./browserTelemetry";
import { recoverFromDynamicImportFetchError } from "./routeChunkRecovery";

const AgentsRoute = lazyRoute(() => import("../routes/AgentsRoute").then((module) => ({ default: module.AgentsRoute })));
const ChatCodingRoute = lazyRoute(() => import("../routes/ChatCodingRoute").then((module) => ({ default: module.ChatCodingRoute })));
const ConfigRoute = lazyRoute(() => import("../routes/ConfigRoute").then((module) => ({ default: module.ConfigRoute })));
const EvolutionRoute = lazyRoute(() => import("../routes/EvolutionRoute").then((module) => ({ default: module.EvolutionRoute })));
const GitRoute = lazyRoute(() => import("../routes/GitRoute").then((module) => ({ default: module.GitRoute })));
const LauncherRoute = lazyRoute(() => import("../routes/LauncherRoute").then((module) => ({ default: module.LauncherRoute })));
const LogsRoute = lazyRoute(() => import("../routes/LogsRoute").then((module) => ({ default: module.LogsRoute })));
const MemoryRoute = lazyRoute(() => import("../routes/MemoryRoute").then((module) => ({ default: module.MemoryRoute })));
const PetRoute = lazyRoute(() => import("../routes/PetRoute").then((module) => ({ default: module.PetRoute })));
const PromptTemplatesRoute = lazyRoute(() => import("../routes/PromptTemplatesRoute").then((module) => ({ default: module.PromptTemplatesRoute })));
const ResetRoute = lazyRoute(() => import("../routes/ResetRoute").then((module) => ({ default: module.ResetRoute })));
const ResearchFlowCanvasRoute = lazyRoute(() => import("../routes/ResearchFlowCanvasRoute").then((module) => ({ default: module.ResearchFlowCanvasRoute })));
const SkillsRoute = lazyRoute(() => import("../routes/SkillsRoute").then((module) => ({ default: module.SkillsRoute })));
const SupervisedReviewRoute = lazyRoute(() => import("../routes/SupervisedReviewRoute").then((module) => ({ default: module.SupervisedReviewRoute })));
const TeamsRoute = lazyRoute(() => import("../routes/TeamsRoute").then((module) => ({ default: module.TeamsRoute })));
const ToolsRoute = lazyRoute(() => import("../routes/ToolsRoute").then((module) => ({ default: module.ToolsRoute })));

function lazyRoute<T extends ComponentType<any>>(loader: () => Promise<{ default: T }>) {
  return lazy(() =>
    loader().catch((error) => {
      if (recoverFromDynamicImportFetchError(error, globalThis.window, postBrowserTelemetry)) {
        return new Promise<{ default: T }>(() => undefined);
      }
      throw error;
    }),
  );
}

function lazyElement(element: ReactNode) {
  return <Suspense fallback={null}>{element}</Suspense>;
}

function routeErrorElement(surface: RouteErrorSurface = "workbench") {
  return <RouteErrorBoundary surface={surface} />;
}

function guardedLazyElement(element: ReactNode, surface: RouteErrorSurface = "workbench") {
  return {
    element: lazyElement(element),
    errorElement: routeErrorElement(surface),
  };
}

export const router = createBrowserRouter([
  {
    path: "/launcher",
    element: <LauncherShell />,
    errorElement: routeErrorElement("launcher"),
    children: [
      { index: true, ...guardedLazyElement(<LauncherRoute />, "launcher") },
    ],
  },
  {
    path: "/",
    element: <AppShell />,
    errorElement: routeErrorElement("workbench"),
    children: [
      { index: true, element: <HomeRedirect /> },
      {
        path: "chat",
        ...guardedLazyElement(
          <WorkbenchDomainRoute domain="chat">
            <ChatCodingRoute />
          </WorkbenchDomainRoute>,
        ),
      },
      {
        path: "chat-rooms",
        element: <LegacyChatRoomsRedirect />,
      },
      {
        path: "supervised-evolution",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="live" />
          </WorkbenchModeRoute>,
        ),
      },
      {
        path: "supervised-evolution/runs",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="runs" />
          </WorkbenchModeRoute>,
        ),
      },
      {
        path: "supervised-evolution/library",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="library" />
          </WorkbenchModeRoute>,
        ),
      },
      {
        path: "supervised-evolution/review",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="supervised_evolution">
            <SupervisedReviewRoute />
          </WorkbenchModeRoute>,
        ),
      },
      {
        path: "self-evolution",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="self_evolution">
            <EvolutionRoute forcedTrack="self" />
          </WorkbenchModeRoute>,
        ),
      },
      { path: "evolution", element: <LegacyEvolutionRedirect /> },
      { path: "agents", ...guardedLazyElement(<AgentsRoute />) },
      { path: "agents/teams", element: <LegacyTeamsRedirect /> },
      { path: "agents/prompts", ...guardedLazyElement(<PromptTemplatesRoute />) },
      { path: "agents/tools", ...guardedLazyElement(<ToolsRoute />) },
      { path: "agents/skills", ...guardedLazyElement(<SkillsRoute />) },
      { path: "agents/memory", element: <LegacyMemoryRedirect to="/memory" /> },
      { path: "agents/memory/effective", element: <LegacyMemoryRedirect to="/memory/effective" /> },
      { path: "agents/memory/agents", element: <LegacyMemoryRedirect to="/memory/agents" /> },
      { path: "agents/memory/manage", element: <LegacyMemoryRedirect to="/memory/manage" /> },
      { path: "agents/memory/sources", element: <LegacyMemoryRedirect to="/memory/sources" /> },
      { path: "agents/memory/knowledge", element: <LegacyMemoryRedirect to="/memory/knowledge" /> },
      { path: "agents/memory/graph", element: <LegacyMemoryRedirect to="/memory/graph" /> },
      { path: "agents/memory/cleanup", element: <LegacyMemoryRedirect to="/memory/cleanup" /> },
      { path: "memory", ...guardedLazyElement(<MemoryRoute forcedView="overview" />) },
      { path: "memory/effective", ...guardedLazyElement(<MemoryRoute forcedView="effective" />) },
      { path: "memory/agents", ...guardedLazyElement(<MemoryRoute forcedView="agents" />) },
      { path: "memory/manage", ...guardedLazyElement(<MemoryRoute forcedView="manage" />) },
      { path: "memory/sources", ...guardedLazyElement(<MemoryRoute forcedView="sources" />) },
      { path: "memory/knowledge", ...guardedLazyElement(<MemoryRoute forcedView="knowledge" />) },
      { path: "memory/graph", ...guardedLazyElement(<MemoryRoute forcedView="graph" />) },
      { path: "memory/cleanup", ...guardedLazyElement(<MemoryRoute forcedView="cleanup" />) },
      { path: "teams", ...guardedLazyElement(<TeamsRoute />) },
      { path: "git", ...guardedLazyElement(<GitRoute />) },
      { path: "logs", ...guardedLazyElement(<LogsRoute />) },
      { path: "research", element: <LegacyTeamsRedirect /> },
      { path: "research/flow-canvas", ...guardedLazyElement(<ResearchFlowCanvasRoute />) },
      { path: "pet", ...guardedLazyElement(<PetRoute />) },
      { path: "reset", ...guardedLazyElement(<ResetRoute />) },
      { path: "config", ...guardedLazyElement(<ConfigRoute />) },
    ],
  },
]);
