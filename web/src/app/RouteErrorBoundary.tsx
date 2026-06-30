import { useRouteError } from "react-router-dom";

import { VButton } from "../components/vui";
import { isDynamicImportFetchError } from "./routeChunkRecovery";

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

const surfaceClass = [
  "grid min-h-screen place-items-center bg-[image:var(--vui-gradient-route-soft)] p-8 text-vui-fg-primary",
  "max-[640px]:p-[18px]",
].join(" ");
const panelClass = [
  "w-[min(560px,100%)] rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-glass p-5 shadow-none backdrop-blur-[14px]",
  "max-[640px]:p-[18px]",
].join(" ");
const kickerClass = "mb-2 mt-0 text-[var(--vui-font-sm)] font-bold text-vui-accent-cool";
const titleClass = "m-0 text-[1.28rem] leading-[1.25] max-[640px]:text-xl";
const detailClass = "mb-0 mt-3 text-[var(--vui-font-chat)] leading-[1.55] text-vui-fg-secondary";
const actionsClass = "mt-[18px] flex flex-wrap gap-2";
const actionButtonClass = "min-w-24";
const technicalClass = "mt-[18px] border-t border-vui-border-subtle pt-[14px]";
const technicalSummaryClass = "cursor-pointer text-[var(--vui-font-sm)] font-bold text-vui-fg-tertiary";
const technicalPreClass = "mt-2.5 max-h-40 overflow-auto whitespace-pre-wrap rounded-[var(--radius-card)] border border-vui-border-subtle bg-[var(--surface-code)] p-3 text-[var(--vui-font-xs)] leading-[1.5] text-vui-fg-primary";

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
    <div className={surfaceClass} data-vui-app={surface} role="alert" aria-live="assertive">
      <section className={panelClass} aria-label={viewModel.title}>
        <p className={kickerClass}>{viewModel.kicker}</p>
        <h1 className={titleClass}>{viewModel.title}</h1>
        <p className={detailClass}>{viewModel.detail}</p>
        <div className={actionsClass}>
          <VButton type="button" variant="primary" className={actionButtonClass} onPress={reloadPage}>
            {viewModel.primaryActionLabel}
          </VButton>
          <VButton type="button" variant="secondary" className={actionButtonClass} onPress={goHome}>
            {viewModel.secondaryActionLabel}
          </VButton>
        </div>
        <details className={technicalClass}>
          <summary className={technicalSummaryClass}>技术摘要</summary>
          <pre className={technicalPreClass}>{viewModel.technicalSummary}</pre>
        </details>
      </section>
    </div>
  );
}
