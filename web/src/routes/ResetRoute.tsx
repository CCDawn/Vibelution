import { ExternalLink, ShieldCheck } from "lucide-react";

import { VRouteHeader } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import styles from "./ResetRoute.styles";

const COPY = {
  zh: {
    title: "Reset 已迁移",
    subtitle: "清理、恢复初始化和开发者维护现在统一由 Launcher 执行。这个旧入口只保留迁移提示，不再读取或执行 Web reset API。",
    owner: "Launcher 维护中心",
    ownerDetail: "Launcher 会生成维护计划、校验 planHash、检查 active work，并记录执行结果。",
    openLauncher: "打开 Launcher",
    retired: "Web Reset API 已退役",
    retiredDetail: "访问 /api/reset/* 会返回 410，避免 Web backend 继续拥有删除能力。",
  },
  en: {
    title: "Reset Moved",
    subtitle: "Cleanup, restore initialization, and developer maintenance are now executed by Launcher. This legacy entry only shows the migration notice and no longer reads or executes the Web reset API.",
    owner: "Launcher Maintenance Center",
    ownerDetail: "Launcher builds the plan, validates planHash, checks active work, and records the execution result.",
    openLauncher: "Open Launcher",
    retired: "Web Reset API retired",
    retiredDetail: "Requests to /api/reset/* now return 410 so the Web backend no longer owns deletion.",
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
        <section className={styles.cardClass}>
          <div className={styles.cardTitleRowClass}>
            <ShieldCheck size={16} />
            <h2 className={styles.cardTitleClass}>{copy.owner}</h2>
          </div>
          <p className={styles.subtitleClass}>{copy.ownerDetail}</p>
        </section>
        <section className={styles.cardClass}>
          <div className={styles.cardTitleRowClass}>
            <ShieldCheck size={16} />
            <h2 className={styles.cardTitleClass}>{copy.retired}</h2>
          </div>
          <p className={styles.subtitleClass}>{copy.retiredDetail}</p>
        </section>
      </main>
    </div>
  );
}
