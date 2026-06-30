import { NavLink } from "react-router-dom";

import { useShellI18n } from "../i18n/useShellI18n";

type AgentManagementSection = "agents" | "prompts" | "tools" | "skills";

const ITEMS: Array<{ key: AgentManagementSection; href: string }> = [
  { key: "agents", href: "/agents" },
  { key: "prompts", href: "/agents/prompts" },
  { key: "tools", href: "/agents/tools" },
  { key: "skills", href: "/agents/skills" },
];

function sectionLabel(section: AgentManagementSection, lang: string) {
  const zh = {
    agents: "Agent",
    prompts: "提示词",
    tools: "工具",
    skills: "技能",
  };
  const en = {
    agents: "Agents",
    prompts: "Prompts",
    tools: "Tools",
    skills: "Skills",
  };
  return (lang === "zh" ? zh : en)[section];
}

const navClass = [
  "mx-3 mt-1.5 inline-flex min-w-0 items-center gap-[3px] rounded-[8px] border border-vui-border-subtle",
  "bg-[image:var(--vui-gradient-route-soft)] p-[3px] shadow-[var(--vui-shadow-inset-accent)]",
  "max-[720px]:w-[calc(100%-24px)] max-[720px]:justify-start max-[720px]:overflow-x-auto",
].join(" ");

const linkClass = [
  "inline-flex min-h-6 min-w-[84px] items-center justify-center whitespace-nowrap rounded-[var(--radius-control)] px-[9px]",
  "text-[var(--vui-font-xs)] font-bold text-vui-fg-secondary no-underline transition-[background,color,box-shadow] duration-150",
  "hover:bg-vui-surface-row-hover hover:text-vui-fg-primary max-[720px]:min-w-max",
].join(" ");

const linkActiveClass = [
  "bg-vui-status-info-bg text-vui-accent-cool shadow-[var(--vui-shadow-inset-accent)]",
].join(" ");

type AgentManagementNavProps = {
  active: AgentManagementSection;
  className?: string;
};

export function AgentManagementNav({ active, className = "" }: AgentManagementNavProps) {
  const { lang } = useShellI18n();
  const label = lang === "zh" ? "Agent 管理导航" : "Agent management navigation";

  return (
    <nav className={className ? `${navClass} ${className}` : navClass} aria-label={label}>
      {ITEMS.map((item) => (
        <NavLink
          key={item.key}
          to={item.href}
          end={item.key === "agents" || item.key === "prompts" || item.key === "tools" || item.key === "skills"}
          className={({ isActive }) =>
            isActive || active === item.key ? `${linkClass} ${linkActiveClass}` : linkClass
          }
        >
          {sectionLabel(item.key, lang)}
        </NavLink>
      ))}
    </nav>
  );
}
