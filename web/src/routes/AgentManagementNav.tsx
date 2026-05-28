import { NavLink } from "react-router-dom";

import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./AgentManagementNav.module.css";

type AgentManagementSection = "agents" | "prompts" | "tools" | "skills" | "memory";

const ITEMS: Array<{ key: AgentManagementSection; href: string }> = [
  { key: "agents", href: "/agents" },
  { key: "prompts", href: "/agents/prompts" },
  { key: "tools", href: "/agents/tools" },
  { key: "skills", href: "/agents/skills" },
  { key: "memory", href: "/agents/memory" },
];

function sectionLabel(section: AgentManagementSection, lang: string) {
  const zh = {
    agents: "Agent",
    prompts: "提示词",
    tools: "工具",
    skills: "技能",
    memory: "记忆",
  };
  const en = {
    agents: "Agents",
    prompts: "Prompts",
    tools: "Tools",
    skills: "Skills",
    memory: "Memory",
  };
  return (lang === "zh" ? zh : en)[section];
}

type AgentManagementNavProps = {
  active: AgentManagementSection;
};

export function AgentManagementNav({ active }: AgentManagementNavProps) {
  const { lang } = useAppI18n();
  const label = lang === "zh" ? "Agent 管理导航" : "Agent management navigation";

  return (
    <nav className={styles.nav} aria-label={label}>
      {ITEMS.map((item) => (
        <NavLink
          key={item.key}
          to={item.href}
          end={item.key === "agents" || item.key === "prompts" || item.key === "tools" || item.key === "skills"}
          className={({ isActive }) =>
            isActive || active === item.key ? `${styles.link} ${styles.linkActive}` : styles.link
          }
        >
          {sectionLabel(item.key, lang)}
        </NavLink>
      ))}
    </nav>
  );
}
