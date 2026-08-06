import { useLocation } from "react-router-dom";

import { VRouteLinkButton } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import styles from "./AgentManagementNav.styles";

export type AgentManagementSection = "agents" | "prompts" | "tools" | "skills";

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

/** Exact path match for agent management section tabs (do not treat /agents/prompts as /agents). */
function isExactSectionPath(pathname: string, href: string) {
  return pathname === href || pathname === `${href}/`;
}

type AgentManagementNavProps = {
  active: AgentManagementSection;
  className?: string;
};

export function AgentManagementNav({ active, className = "" }: AgentManagementNavProps) {
  const { lang } = useShellI18n();
  const location = useLocation();
  const label = lang === "zh" ? "Agent 管理导航" : "Agent management navigation";

  return (
    <nav className={className ? `${styles.navClass} ${className}` : styles.navClass} aria-label={label}>
      {ITEMS.map((item) => {
        const routeActive = isExactSectionPath(location.pathname, item.href) || active === item.key;
        return (
          <VRouteLinkButton
            key={item.key}
            chrome="shell-nav"
            to={item.href}
            className={routeActive ? `${styles.linkClass} ${styles.linkActiveClass}` : styles.linkClass}
            aria-current={routeActive ? "page" : undefined}
          >
            {sectionLabel(item.key, lang)}
          </VRouteLinkButton>
        );
      })}
    </nav>
  );
}
