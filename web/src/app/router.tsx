import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "./AppShell";
import { GlobalCommandSurfaces } from "./GlobalCommandSurfaces";
import { LauncherShell } from "./LauncherShell";
import { RouteLoadingShell, type RouteLoadingLayout } from "./RouteLoadingShell";
import { WorkflowLoadingBoundary } from "../routes/teams/generic/WorkflowLoadingBoundary";
import { RouteErrorBoundary, type RouteErrorSurface } from "./RouteErrorBoundary";
import { HomeRedirect } from "../routes/HomeRedirect";
import { WorkbenchDomainRoute } from "../routes/WorkbenchDomainRoute";
import { WorkbenchModeRoute } from "../routes/WorkbenchModeRoute";
import { postBrowserTelemetry } from "./browserTelemetry";
import { createReloadGracePromise, recoverFromDynamicImportFetchError } from "./routeChunkRecovery";

const AgentsRoute = lazyRoute(loadAgentsRouteChunk);
// The folder must not be named `aux` — AUX is a reserved device name on
// Windows and git cannot index files under it.
const AuxConversationsRoute = lazyRoute(() => import("../routes/auxConversations/AuxConversationsRoute").then((module) => ({ default: module.AuxConversationsRoute })));
type ChatCodingRouteModule = typeof import("../routes/ChatCodingRoute");

/**
 * Telemetry-free chat chunk import, shared by the lazy route graph and the
 * shell's idle warm pass (the warm pass must not emit navigation chunk
 * telemetry outside a real navigation).
 */
export function importChatCodingRouteChunk(): Promise<ChatCodingRouteModule> {
  return import("../routes/ChatCodingRoute");
}

export function loadChatCodingRouteChunk(
  loader: () => Promise<ChatCodingRouteModule> = importChatCodingRouteChunk,
) {
  const startedAt = nowMs();
  postBrowserTelemetry({
    phase: "navigation",
    eventCode: "browser.chat_route.chunk_load_started",
    message: "Chat route chunk load started.",
    fields: {
      pathname: currentPathname(),
    },
  });
  return loader().then((module) => {
    postBrowserTelemetry({
      phase: "navigation",
      eventCode: "browser.chat_route.chunk_loaded",
      message: "Chat route chunk loaded.",
      fields: {
        durationMs: elapsedMs(startedAt),
        pathname: currentPathname(),
      },
    });
    return { default: module.ChatCodingRoute };
  });
}

const ChatCodingRoute = lazyRoute(loadChatCodingRouteChunk);
const FinanceRoute = lazyRoute(() => import("../routes/FinanceRoute").then((module) => ({ default: module.FinanceRoute })));
const CompanionsRoute = lazyRoute(loadCompanionsRouteChunk);
const ConfigRoute = lazyRoute(() => import("../routes/ConfigRoute").then((module) => ({ default: module.ConfigRoute })));
const EvolutionRoute = lazyRoute(loadEvolutionRouteChunk);
const GitRoute = lazyRoute(() => import("../routes/GitRoute").then((module) => ({ default: module.GitRoute })));
const KernelTaskCenterRoute = lazyRoute(() => import("../routes/KernelTaskCenterRoute").then((module) => ({ default: module.KernelTaskCenterRoute })));
const LauncherRoute = lazyRoute(() => import("../routes/LauncherRoute").then((module) => ({ default: module.LauncherRoute })));
const LauncherToolsRoute = lazyRoute(() => import("../routes/LauncherToolsRoute").then((module) => ({ default: module.LauncherToolsRoute })));
const LogsRoute = lazyRoute(() => import("../routes/LogsRoute").then((module) => ({ default: module.LogsRoute })));
const MemoryRoute = lazyRoute(loadMemoryRouteChunk);
const PetRoute = lazyRoute(() => import("../routes/PetRoute").then((module) => ({ default: module.PetRoute })));
const DesktopAssistantRoute = lazyRoute(() => import("../routes/desktopPet/DesktopAssistantRoute").then((module) => ({ default: module.DesktopAssistantRoute })));
const LauncherAssistantRoute = lazyRoute(() => import("../routes/desktopPet/LauncherAssistantRoute").then((module) => ({ default: module.LauncherAssistantRoute })));
const LauncherAssistantEmbeddedRoute = lazyRoute(() => import("../routes/desktopPet/LauncherAssistantRoute").then((module) => ({ default: module.LauncherAssistantEmbeddedRoute })));
const PersonalAssistantRoute = lazyRoute(() => import("../routes/PersonalAssistantRoute").then((module) => ({ default: module.PersonalAssistantRoute })));
const PromptTemplatesRoute = lazyRoute(() => import("../routes/PromptTemplatesRoute").then((module) => ({ default: module.PromptTemplatesRoute })));
const ResetRoute = lazyRoute(() => import("../routes/ResetRoute").then((module) => ({ default: module.ResetRoute })));
const SkillsRoute = lazyRoute(() => import("../routes/SkillsRoute").then((module) => ({ default: module.SkillsRoute })));
const SupervisedReviewRoute = lazyRoute(() => import("../routes/SupervisedReviewRoute").then((module) => ({ default: module.SupervisedReviewRoute })));
const TeamsRoute = lazyRoute(loadTeamsRouteChunk);
const ToolsRoute = lazyRoute(() => import("../routes/ToolsRoute").then((module) => ({ default: module.ToolsRoute })));
const UsageRoute = lazyRoute(() => import("../routes/UsageRoute").then((module) => ({ default: module.UsageRoute })));

/**
 * Primary navigation chunk loaders, shared by the lazy route graph above and
 * the shell's hover/focus preload + idle warm pass (AppShell.tsx). Keeping the
 * dynamic import specifiers here means a preload warms the exact chunk the
 * route navigation will consume.
 */
export function loadAgentsRouteChunk() {
  return import("../routes/AgentsRoute").then((module) => ({ default: module.AgentsRoute }));
}

export function loadCompanionsRouteChunk() {
  return import("../routes/CompanionsRoute").then((module) => ({ default: module.CompanionsRoute }));
}

export function loadEvolutionRouteChunk() {
  return import("../routes/EvolutionRoute").then((module) => ({ default: module.EvolutionRoute }));
}

export function loadMemoryRouteChunk() {
  return import("../routes/MemoryRoute").then((module) => ({ default: module.MemoryRoute }));
}

export function loadTeamsRouteChunk() {
  return import("../routes/TeamsRoute").then((module) => ({ default: module.TeamsRoute }));
}

/**
 * Wraps a navigation chunk loader with stale-asset recovery. When a recovery
 * reload is requested, the returned promise stays pending through a short
 * grace window (the reload may still tear down this document) and then
 * rejects with the original error, so the route errorElement — not an
 * eternal suspension — owns the failure when the reload was vetoed.
 */
export function loadRouteChunkWithRecovery<T extends ComponentType<any>>(
  loader: () => Promise<{ default: T }>,
): Promise<{ default: T }> {
  return loader().catch((error) => {
    if (recoverFromDynamicImportFetchError(error, globalThis.window, postBrowserTelemetry)) {
      return createReloadGracePromise<{ default: T }>(error, {
        onDegrade: (degradedError) => {
          postBrowserTelemetry({
            phase: "recovery",
            eventCode: "browser.route_chunk_recovery.reload_vetoed",
            message: "Route chunk recovery reload did not take effect; surfacing the route error boundary.",
            level: "error",
            fields: {
              pathname: currentPathname(),
              errorMessage: degradedError instanceof Error ? degradedError.message : String(degradedError ?? ""),
            },
          });
        },
      });
    }
    throw error;
  });
}

function lazyRoute<T extends ComponentType<any>>(loader: () => Promise<{ default: T }>) {
  return lazy(() => loadRouteChunkWithRecovery(loader));
}

function nowMs(): number {
  return typeof performance === "undefined" ? Date.now() : performance.now();
}

function elapsedMs(startedAt: number): number {
  return Math.max(0, Math.round(nowMs() - startedAt));
}

function currentPathname(): string {
  return typeof window === "undefined" ? "" : window.location.pathname;
}


function lazyElement(
  element: ReactNode,
  surface: RouteErrorSurface = "workbench",
  loadingLayout: RouteLoadingLayout = "default",
) {
  const content = <Suspense fallback={<RouteLoadingShell surface={surface} layout={loadingLayout} />}>{element}</Suspense>;
  return loadingLayout === "teams" ? <WorkflowLoadingBoundary>{content}</WorkflowLoadingBoundary> : content;
}

function routeErrorElement(surface: RouteErrorSurface = "workbench") {
  return <RouteErrorBoundary surface={surface} />;
}

function guardedLazyElement(
  element: ReactNode,
  surface: RouteErrorSurface = "workbench",
  loadingLayout: RouteLoadingLayout = "default",
) {
  return {
    element: lazyElement(element, surface, loadingLayout),
    errorElement: routeErrorElement(surface),
  };
}

export const router = createBrowserRouter([
  {
    path: "/launcher-assistant",
    ...guardedLazyElement(<LauncherAssistantRoute />, "launcher"),
  },
  {
    path: "/desktop-assistant",
    ...guardedLazyElement(<DesktopAssistantRoute />, "workbench"),
  },
  {
    // Legacy desktop-pet URL: the pet and the personal assistant are one
    // surface now, so old shells and bookmarks land on the unified window.
    path: "/desktop-pet",
    element: <Navigate to="/desktop-assistant" replace />,
  },
  {
    path: "/launcher",
    element: <LauncherShell />,
    errorElement: routeErrorElement("launcher"),
    children: [
      { index: true, ...guardedLazyElement(<LauncherRoute />, "launcher", "launcher") },
      { path: "tools", ...guardedLazyElement(<LauncherToolsRoute />, "launcher", "launcher-tools") },
      { path: "assistant", ...guardedLazyElement(<LauncherAssistantEmbeddedRoute />, "launcher", "launcher") },
    ],
  },
  {
    path: "/",
    // 壳层与全局命令面并列：GlobalCommandSurfaces 只渲染 portal 对话框，
    // 不进 AppShell 布局树（AppShell.tsx 当前由并行会话 claim）。
    element: (
      <>
        <AppShell />
        <GlobalCommandSurfaces />
      </>
    ),
    errorElement: routeErrorElement("workbench"),
    children: [
      { index: true, element: <HomeRedirect /> },
      {
        path: "chat",
        ...guardedLazyElement(
          <WorkbenchDomainRoute domain="chat">
            <ChatCodingRoute />
          </WorkbenchDomainRoute>,
          "workbench",
          "chat",
        ),
      },
      {
        path: "finance",
        ...guardedLazyElement(<WorkbenchDomainRoute domain="chat"><FinanceRoute /></WorkbenchDomainRoute>, "workbench", "finance"),
      },
      {
        path: "personal-assistant",
        ...guardedLazyElement(<WorkbenchDomainRoute domain="chat"><PersonalAssistantRoute /></WorkbenchDomainRoute>, "workbench", "chat"),
      },
      {
        path: "companions",
        ...guardedLazyElement(
          <WorkbenchDomainRoute domain="chat">
            <CompanionsRoute />
          </WorkbenchDomainRoute>,
          "workbench",
          "companions",
        ),
      },
      {
        // P2 nav collapse: aggregated Evolution entry (supervised + self sections via
        // the in-page track toggle). `/evolution` itself stays a retired legacy URL;
        // forced deep links below keep /supervised-evolution and /self-evolution alive.
        path: "evolution/workspace",
        ...guardedLazyElement(
          <WorkbenchDomainRoute domain="evolution">
            <EvolutionRoute />
          </WorkbenchDomainRoute>,
          "workbench",
          "evolution",
        ),
      },
      {
        path: "supervised-evolution",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="live" />
          </WorkbenchModeRoute>,
          "workbench",
          "evolution",
        ),
      },
      {
        path: "supervised-evolution/runs",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="runs" />
          </WorkbenchModeRoute>,
          "workbench",
          "evolution-runs",
        ),
      },
      {
        path: "supervised-evolution/library",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="library" />
          </WorkbenchModeRoute>,
          "workbench",
          "evolution-library",
        ),
      },
      {
        path: "supervised-evolution/review",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="supervised_evolution">
            <SupervisedReviewRoute />
          </WorkbenchModeRoute>,
          "workbench",
          "review",
        ),
      },
      {
        path: "self-evolution",
        ...guardedLazyElement(
          <WorkbenchModeRoute mode="self_evolution">
            <EvolutionRoute forcedTrack="self" />
          </WorkbenchModeRoute>,
          "workbench",
          "evolution",
        ),
      },
      { path: "agents", ...guardedLazyElement(<AgentsRoute />, "workbench", "agents") },
      { path: "agents/prompts", ...guardedLazyElement(<PromptTemplatesRoute />, "workbench", "prompts") },
      { path: "agents/tools", ...guardedLazyElement(<ToolsRoute />, "workbench", "tools") },
      { path: "agents/skills", ...guardedLazyElement(<SkillsRoute />, "workbench", "skills") },
      { path: "memory", ...guardedLazyElement(<MemoryRoute forcedView="personal" />, "workbench", "memory-browse") },
      { path: "memory/team", ...guardedLazyElement(<MemoryRoute forcedView="team" />, "workbench", "memory-cards") },
      { path: "memory/library", ...guardedLazyElement(<MemoryRoute forcedView="library" />, "workbench", "memory-cards") },
      { path: "memory/agents", ...guardedLazyElement(<MemoryRoute forcedView="personal" />, "workbench", "memory-browse") },
      { path: "memory/knowledge", ...guardedLazyElement(<MemoryRoute forcedView="knowledge" />, "workbench", "memory-knowledge") },
      { path: "memory/manage", ...guardedLazyElement(<MemoryRoute forcedView="manage" />, "workbench", "memory-ops") },
      { path: "memory/sources", ...guardedLazyElement(<MemoryRoute forcedView="manage" />, "workbench", "memory-ops") },
      { path: "memory/effective", ...guardedLazyElement(<MemoryRoute forcedView="manage" />, "workbench", "memory-ops") },
      { path: "memory/cleanup", ...guardedLazyElement(<MemoryRoute forcedView="cleanup" />, "workbench", "memory-ops") },
      { path: "memory/graph", ...guardedLazyElement(<MemoryRoute forcedView="graph" />, "workbench", "memory-graph") },
      { path: "teams", ...guardedLazyElement(<TeamsRoute />, "workbench", "teams") },
      { path: "kernel", ...guardedLazyElement(<KernelTaskCenterRoute />, "workbench", "kernel") },
      { path: "aux", ...guardedLazyElement(<AuxConversationsRoute />, "workbench", "aux") },
      { path: "git", ...guardedLazyElement(<GitRoute />, "workbench", "git") },
      { path: "usage", ...guardedLazyElement(<UsageRoute />, "workbench", "usage") },
      { path: "logs", ...guardedLazyElement(<LogsRoute />, "workbench", "logs") },
      { path: "pet", ...guardedLazyElement(<PetRoute />, "workbench", "pet") },
      { path: "reset", ...guardedLazyElement(<ResetRoute />, "workbench", "reset") },
      { path: "config", ...guardedLazyElement(<ConfigRoute />, "workbench", "config") },
    ],
  },
]);
