import { type RouteErrorSurface } from "./RouteErrorBoundary";
import styles from "./RouteLoadingShell.styles";

export type RouteLoadingShellProps = {
  label?: string;
  meta?: string;
  surface?: RouteErrorSurface;
};

export function RouteLoadingShell({
  label,
  meta = "加载界面模块",
  surface = "workbench",
}: RouteLoadingShellProps) {
  const resolvedLabel = label ?? (surface === "launcher" ? "正在打开启动器" : "正在打开工作台");
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-vui-app={surface}
      className={styles.surface}
    >
      <div className={styles.panel}>
        <strong className={styles.title}>{resolvedLabel}</strong>
        <span className={styles.meta}>{meta}</span>
      </div>
    </div>
  );
}
