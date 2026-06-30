import { useRouteError } from "react-router-dom";

import { VButton } from "../components/vui";
import { isDynamicImportFetchError } from "./routeChunkRecovery";
import styles from "./RouteErrorBoundary.styles";

export type RouteErrorSurface = "workbench" | "launcher";

export type RouteErrorBoundaryViewModel = {
  kicker: string;
  title: string;
  detail: string;
  primaryActionLabel: string;
  secondaryActionLabel: string;
  technicalSummary: string;
  isDynamicImportFailure: boolean;
};

function compactTechnicalSummary(error: unknown, limit = 900) {
  const message = error instanceof Error
    ? `${error.name}: ${error.message}${error.stack ? `\n${error.stack}` : ""}`
    : String(error ?? "");
  const compacted = message.replace(/\s+\n/g, "\n").trim();
  if (compacted.length <= limit) {
    return compacted || "Unknown route error";
  }
  return `${compacted.slice(0, Math.max(0, limit - 3))}...`;
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
    technicalSummary: compactTechnicalSummary(error),
    isDynamicImportFailure,
  };
}

export function RouteErrorBoundary({ surface = "workbench" }: { surface?: RouteErrorSurface }) {
  const error = useRouteError();
  const viewModel = buildRouteErrorBoundaryViewModel(error, surface);

  const reloadPage = () => {
    globalThis.window?.location.reload();
  };
  const goHome = () => {
    const target = surface === "launcher" ? "/launcher" : "/chat";
    globalThis.window?.location.assign(target);
  };

  return (
    <div className={styles.surfaceClass} data-vui-app={surface} role="alert" aria-live="assertive">
      <section className={styles.panelClass} aria-label={viewModel.title}>
        <p className={styles.kickerClass}>{viewModel.kicker}</p>
        <h1 className={styles.titleClass}>{viewModel.title}</h1>
        <p className={styles.detailClass}>{viewModel.detail}</p>
        <div className={styles.actionsClass}>
          <VButton type="button" variant="primary" className={styles.actionButtonClass} onPress={reloadPage}>
            {viewModel.primaryActionLabel}
          </VButton>
          <VButton type="button" variant="secondary" className={styles.actionButtonClass} onPress={goHome}>
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
