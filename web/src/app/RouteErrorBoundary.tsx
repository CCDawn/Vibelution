import { useEffect } from "react";
import { isRouteErrorResponse, useRouteError } from "react-router-dom";

import { VButton } from "../components/vui/primitives/VButton";
import { type BrowserTelemetryEventInput, postBrowserTelemetry } from "./browserTelemetry";
import { allowNextWorkbenchWindowUnload } from "./projectCloseGuard";
import { isDynamicImportFetchError } from "./routeChunkRecovery";
import styles from "./RouteErrorBoundary.styles";

export type RouteErrorSurface = "workbench" | "launcher";

export type RouteErrorActionKind = "reload" | "navigate";

export type RouteErrorBoundaryViewModel = {
  kicker: string;
  title: string;
  detail: string;
  primaryActionLabel: string;
  secondaryActionLabel: string;
  primaryAction: RouteErrorActionKind;
  secondaryAction: RouteErrorActionKind;
  technicalSummary: string;
  isDynamicImportFailure: boolean;
};

const reportedRouteErrorKeys = new Set<string>();

function stringifyUnknownValue(value: unknown) {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value) ?? String(value ?? "");
  } catch {
    return String(value ?? "");
  }
}

function compactTechnicalSummary(error: unknown, limit = 900) {
  let message: string;
  if (isRouteErrorResponse(error)) {
    const statusText = error.statusText ? ` ${error.statusText}` : "";
    const dataText =
      error.data === undefined || error.data === null
        ? ""
        : ` ${stringifyUnknownValue(error.data).replace(/\s+/g, " ").trim()}`;
    message = `HTTP ${error.status}${statusText}${dataText}`;
  } else if (error instanceof Error) {
    message = `${error.name}: ${error.message}${error.stack ? `\n${error.stack}` : ""}`;
  } else {
    message = stringifyUnknownValue(error);
  }
  const compacted = message.replace(/\s+\n/g, "\n").trim();
  if (compacted.length <= limit) {
    return compacted || "Unknown route error";
  }
  return `${compacted.slice(0, Math.max(0, limit - 3))}...`;
}

function compactErrorText(error: unknown, limit: number) {
  const text = error instanceof Error
    ? `${error.name}: ${error.message}`
    : String(error ?? "Unknown route error");
  const compacted = text.replace(/\s+/g, " ").trim();
  if (compacted.length <= limit) {
    return compacted || "Unknown route error";
  }
  return `${compacted.slice(0, Math.max(0, limit - 3))}...`;
}

function currentPathname() {
  return typeof window === "undefined" ? "" : window.location.pathname;
}

export function buildRouteErrorBoundaryViewModel(
  error: unknown,
  surface: RouteErrorSurface = "workbench",
): RouteErrorBoundaryViewModel {
  const isDynamicImportFailure = isDynamicImportFetchError(error);
  const targetName = surface === "launcher" ? "Launcher" : "工作台";

  if (isDynamicImportFailure) {
    return {
      kicker: surface === "launcher" ? "Launcher 资源已更新" : "前端资源已更新",
      title: surface === "launcher" ? "Launcher 需要刷新" : "工作台需要刷新",
      detail: `当前窗口还在使用旧版前端入口，关联的动态资源已经更新或不可用。刷新后会重新加载最新 ${targetName}；如果刚刚关闭了项目，请先通过 Launcher 重新启动。`,
      primaryActionLabel: "刷新前端",
      secondaryActionLabel: "返回入口",
      primaryAction: "reload",
      secondaryAction: "navigate",
      technicalSummary: compactTechnicalSummary(error),
      isDynamicImportFailure,
    };
  }

  if (isRouteErrorResponse(error) && error.status === 404) {
    return {
      kicker: surface === "launcher" ? "Launcher 页面不存在" : "工作台页面不存在",
      title: "页面不存在",
      detail: `请求的地址没有对应的页面。请确认 URL 是否输入正确，或返回${targetName}入口继续操作。`,
      primaryActionLabel: surface === "launcher" ? "返回入口" : "返回工作台",
      secondaryActionLabel: "刷新前端",
      primaryAction: "navigate",
      secondaryAction: "reload",
      technicalSummary: compactTechnicalSummary(error),
      isDynamicImportFailure,
    };
  }

  if (isRouteErrorResponse(error)) {
    return {
      kicker: surface === "launcher" ? "Launcher 页面异常" : "工作台页面异常",
      title: `${surface === "launcher" ? "Launcher" : "工作台"}页面加载失败（HTTP ${error.status}）`,
      detail: "页面加载请求返回了错误状态。可以先刷新前端重试；如果仍然失败，请保留当前日志继续排查。",
      primaryActionLabel: "刷新前端",
      secondaryActionLabel: "返回入口",
      primaryAction: "reload",
      secondaryAction: "navigate",
      technicalSummary: compactTechnicalSummary(error),
      isDynamicImportFailure,
    };
  }

  return {
    kicker: surface === "launcher" ? "Launcher 页面异常" : "工作台页面异常",
    title: surface === "launcher" ? "Launcher 页面加载失败" : "工作台页面加载失败",
    detail: "页面渲染过程中出现异常。可以先刷新前端；如果刷新后仍然失败，请保留当前日志继续排查。",
    primaryActionLabel: "刷新前端",
    secondaryActionLabel: "返回入口",
    primaryAction: "reload",
    secondaryAction: "navigate",
    technicalSummary: compactTechnicalSummary(error),
    isDynamicImportFailure,
  };
}

export function buildRouteErrorTelemetryEvent(
  error: unknown,
  surface: RouteErrorSurface = "workbench",
): BrowserTelemetryEventInput {
  const viewModel = buildRouteErrorBoundaryViewModel(error, surface);
  return {
    phase: "error",
    eventCode: "browser.route.error",
    message: viewModel.isDynamicImportFailure
      ? `${surface} route chunk failed to load`
      : `${surface} route render failed`,
    level: "error",
    fields: {
      surface,
      pathname: currentPathname(),
      isDynamicImportFailure: viewModel.isDynamicImportFailure,
      title: viewModel.title,
      errorName: error instanceof Error ? error.name : "Unknown",
      errorMessage: compactErrorText(error, 240),
      technicalSummary: viewModel.technicalSummary,
    },
  };
}

export function resetRouteErrorTelemetryForTests() {
  reportedRouteErrorKeys.clear();
}

export function reportRouteErrorBoundary(
  error: unknown,
  surface: RouteErrorSurface = "workbench",
) {
  const event = buildRouteErrorTelemetryEvent(error, surface);
  const key = [
    surface,
    String(event.fields?.isDynamicImportFailure ?? false),
    String(event.fields?.technicalSummary ?? "").slice(0, 240),
  ].join("|");
  if (reportedRouteErrorKeys.has(key)) {
    return;
  }
  reportedRouteErrorKeys.add(key);
  postBrowserTelemetry(event);
}

export function RouteErrorBoundary({ surface = "workbench" }: { surface?: RouteErrorSurface }) {
  const error = useRouteError();
  const viewModel = buildRouteErrorBoundaryViewModel(error, surface);

  useEffect(() => {
    reportRouteErrorBoundary(error, surface);
  }, [error, surface]);

  const reloadPage = () => {
    // Parent AppShell may still arm beforeunload; pass it so Edge does not flash
    // a non-actionable "重新加载应用?" dialog over this recovery page.
    allowNextWorkbenchWindowUnload();
    globalThis.window?.location.reload();
  };
  const goHome = () => {
    allowNextWorkbenchWindowUnload();
    const target = surface === "launcher" ? "/launcher" : "/chat";
    globalThis.window?.location.assign(target);
  };

  const primaryOnPress = viewModel.primaryAction === "navigate" ? goHome : reloadPage;
  const secondaryOnPress = viewModel.secondaryAction === "navigate" ? goHome : reloadPage;

  return (
    <div className={styles.surfaceClass} data-vui-app={surface} role="alert" aria-live="assertive">
      <section className={styles.panelClass} aria-label={viewModel.title}>
        <p className={styles.kickerClass}>{viewModel.kicker}</p>
        <h1 className={styles.titleClass}>{viewModel.title}</h1>
        <p className={styles.detailClass}>{viewModel.detail}</p>
        <div className={styles.actionsClass}>
          <VButton type="button" variant="primary" className={styles.actionButtonClass} onPress={primaryOnPress}>
            {viewModel.primaryActionLabel}
          </VButton>
          <VButton type="button" variant="secondary" className={styles.actionButtonClass} onPress={secondaryOnPress}>
            {viewModel.secondaryActionLabel}
          </VButton>
        </div>
        <details className={styles.technicalClass}>
          <summary className={styles.technicalSummaryClass}>技术摘要</summary>
          <pre className={styles.technicalPreClass}>{viewModel.technicalSummary}</pre>
        </details>
      </section>
    </div>
  );
}
