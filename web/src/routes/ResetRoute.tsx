import { ExternalLink, ShieldCheck } from "lucide-react";

import { VRouteHeader } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";

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

const routeClass = "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] bg-[var(--surface-page)]";
const headerClass = "mx-2.5 mt-2 min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-gradient-route-soft),color-mix(in_srgb,var(--surface-panel)_86%,transparent)] shadow-[var(--vui-shadow-hairline)]";
const headerActionsClass = "flex items-center justify-end gap-2";
const secondaryButtonClass = "inline-flex min-h-8 items-center justify-center gap-[7px] rounded-lg border border-vui-border-soft bg-[var(--surface-card)] px-2.5 py-1.5 text-[var(--vui-font-xs)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary";
const workspaceClass = "grid min-h-0 grid-cols-[minmax(0,1fr)_minmax(320px,390px)] items-start gap-2 px-2.5 pb-2.5 pt-2 max-[1120px]:grid-cols-1";
const cardClass = "min-h-0 rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-2";
const cardTitleRowClass = "mb-1.5 flex items-center gap-1.5 text-vui-fg-primary";
const cardTitleClass = "m-0 text-[0.94rem] font-bold";
const subtitleClass = "m-0 min-w-0 truncate text-[var(--route-topbar-subtitle-size)] leading-[1.25] text-vui-fg-secondary";

export function ResetRoute() {
  const { lang } = useShellI18n();
  const copy = COPY[lang];

  return (
    <div className={routeClass} data-reset-retired="launcher-owned">
      <VRouteHeader
        className={headerClass}
        eyebrow="Reset"
        title={copy.title}
        meta={copy.subtitle}
        actions={(
          <div className={headerActionsClass}>
            <a className={secondaryButtonClass} href="/launcher" target="_blank" rel="noreferrer">
              <ExternalLink size={15} />
              {copy.openLauncher}
            </a>
          </div>
        )}
      />

      <main className={workspaceClass}>
        <section className={cardClass}>
          <div className={cardTitleRowClass}>
            <ShieldCheck size={16} />
            <h2 className={cardTitleClass}>{copy.owner}</h2>
          </div>
          <p className={subtitleClass}>{copy.ownerDetail}</p>
        </section>
        <section className={cardClass}>
          <div className={cardTitleRowClass}>
            <ShieldCheck size={16} />
            <h2 className={cardTitleClass}>{copy.retired}</h2>
          </div>
          <p className={subtitleClass}>{copy.retiredDetail}</p>
        </section>
      </main>
    </div>
  );
}
