import { NavLink } from "react-router-dom";

import { useShellI18n } from "../i18n/useShellI18n";
import styles from "./AgentManagementNav.styles";

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




type AgentManagementNavProps = {
  active: AgentManagementSection;
  className?: string;
};

export function AgentManagementNav({ active, className = "" }: AgentManagementNavProps) {
  const { lang } = useShellI18n();
  const label = lang === "zh" ? "Agent 管理导航" : "Agent management navigation";

  return (
    <nav className={className ? `${styles.navClass} ${className}` : styles.navClass} aria-label={label}>
      {ITEMS.map((item) => (
        <NavLink
          key={item.key}
          to={item.href}
          end={item.key === "agents" || item.key === "prompts" || item.key === "tools" || item.key === "skills"}
          className={({ isActive }) =>
            isActive || active === item.key ? `${styles.linkClass} ${styles.linkActiveClass}` : styles.linkClass
          }
        >
          {sectionLabel(item.key, lang)}
        </NavLink>
      ))}
    </nav>
  );
}
