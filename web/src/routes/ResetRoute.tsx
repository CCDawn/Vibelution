import { AlertTriangle, CheckCircle2, ExternalLink, ShieldCheck } from "lucide-react";

import { VRouteHeader } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import styles from "./ResetRoute.styles";

const COPY = {
  zh: {
    title: "Reset 已迁移",
    subtitle: "清理、恢复初始化和开发者维护现在统一由 Launcher 执行。这个旧入口只保留迁移提示，不再读取或执行 Web reset API。",
    status: "退役入口",
    statusDetail: "Reset 的删除与清理职责已从 Web 工作台移交给 Launcher；这里仅保留迁移状态和安全边界。",
    owner: "Launcher 维护中心",
    ownerDetail: "在 Launcher 中选择维护 profile，先预览计划，再由 active work guard 与 planHash 校验执行。",
    openLauncher: "打开 Launcher",
    launcherMeta: "维护入口 /launcher",
    riskTitle: "边界与风险",
    riskLead: "这些边界保持直接可见，避免旧入口被误认为还能删除数据。",
    retired: "Web Reset API 已退役",
    retiredDetail: "访问 /api/reset/* 会返回 410，避免 Web backend 继续拥有删除能力。",
    noAction: "不恢复旧动作链",
    noActionDetail: "本页不读取 summary、preview 或 execute，也不会触发 chat workspace 清理。",
    launcherOwned: "Launcher 接管执行",
    launcherOwnedDetail: "实际清理、恢复初始化和开发者维护都在 Launcher 中完成并记录结果。",
  },
  en: {
    title: "Reset Moved",
    subtitle: "Cleanup, restore initialization, and developer maintenance are now executed by Launcher. This legacy entry only shows the migration notice and no longer reads or executes the Web reset API.",
    status: "Retired entry",
    statusDetail: "Reset deletion and cleanup ownership has moved from the Web workbench to Launcher; this page only keeps migration status and safety boundaries.",
    owner: "Launcher Maintenance Center",
    ownerDetail: "Choose a maintenance profile in Launcher, preview the plan, then let the active-work guard and planHash validation handle execution.",
    openLauncher: "Open Launcher",
    launcherMeta: "Maintenance entry /launcher",
    riskTitle: "Boundaries and risk",
    riskLead: "These boundaries stay visible so the retired entry is not mistaken for a data-deletion surface.",
    retired: "Web Reset API retired",
    retiredDetail: "Requests to /api/reset/* now return 410 so the Web backend no longer owns deletion.",
    noAction: "Old action chain stays retired",
    noActionDetail: "This page does not read summary, preview, or execute endpoints, and it does not reset chat workspace state.",
    launcherOwned: "Launcher owns execution",
    launcherOwnedDetail: "Cleanup, restore initialization, and developer maintenance are completed and recorded in Launcher.",
  },
} as const;


export function ResetRoute() {
  const { lang } = useShellI18n();
  const copy = COPY[lang];

  return (
    <div className={styles.routeClass} data-reset-retired="launcher-owned">
      <VRouteHeader
        className={styles.headerClass}
        eyebrow="Reset"
        title={copy.title}
        meta={copy.subtitle}
        actions={(
          <div className={styles.headerActionsClass}>
            <a className={styles.secondaryButtonClass} href="/launcher" target="_blank" rel="noreferrer">
              <ExternalLink size={15} />
              {copy.openLauncher}
            </a>
          </div>
        )}
      />

      <main className={styles.workspaceClass}>
        <div className={styles.primaryColumnClass}>
          <section className={styles.statusStripClass} data-reset-status="retired">
            <span className={styles.statusIconClass}>
              <ShieldCheck size={16} />
            </span>
            <div className={styles.copyStackClass}>
              <p className={styles.statusLabelClass}>{copy.status}</p>
              <p className={styles.copyTextClass}>{copy.statusDetail}</p>
            </div>
          </section>

          <section className={styles.launcherPanelClass} data-reset-action="launcher-maintenance">
            <div className={styles.cardTitleRowClass}>
              <ExternalLink size={16} />
              <h2 className={styles.cardTitleClass}>{copy.owner}</h2>
            </div>
            <p className={styles.copyTextClass}>{copy.ownerDetail}</p>
            <div className={styles.actionRowClass}>
              <a className={styles.secondaryButtonClass} href="/launcher" target="_blank" rel="noreferrer">
                <ExternalLink size={15} />
                {copy.openLauncher}
              </a>
              <span className={styles.actionMetaClass}>{copy.launcherMeta}</span>
            </div>
          </section>
        </div>

        <aside className={styles.riskPanelClass} data-reset-risk="web-api-retired">
          <div className={styles.cardTitleRowClass}>
            <AlertTriangle size={16} />
            <h2 className={styles.cardTitleClass}>{copy.riskTitle}</h2>
          </div>
          <p className={styles.copyTextClass}>{copy.riskLead}</p>
          <div className={styles.riskListClass}>
            {[
              [copy.retired, copy.retiredDetail],
              [copy.noAction, copy.noActionDetail],
              [copy.launcherOwned, copy.launcherOwnedDetail],
            ].map(([title, detail]) => (
              <div key={title} className={styles.riskItemClass}>
                <CheckCircle2 size={14} />
                <div className={styles.copyStackClass}>
                  <strong>{title}</strong>
                  <small>{detail}</small>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </main>
    </div>
  );
}
