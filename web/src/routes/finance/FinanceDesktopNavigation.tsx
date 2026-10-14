import { Bot, BookOpen, MessageSquare, PanelLeftClose, Settings2, TrendingUp, Wallet } from "lucide-react";
import { VButton, VIconButton, VRouteLinkButton } from "../../components/vui";
import { FINANCE_WORKSPACE_GROUPS } from "./financeWorkspaceNavigation";
import styles from "./FinanceDesktopNavigation.styles";

const icons = { research: MessageSquare, market: TrendingUp, assets: Wallet, library: BookOpen };

export function FinanceDesktopNavigation({ area, zh, displayName, modelLabel, configHref, onNavigate, onCollapse }: {
  area: string; zh: boolean; displayName: string; modelLabel?: string; configHref: string;
  onNavigate: (area: string) => void; onCollapse: () => void;
}) {
  return <div className={styles.root} data-finance-desktop-navigation>
    <header className={styles.heading}><TrendingUp size={17} className={styles.icon} /><strong className={styles.brand}>{zh ? "A股智能体" : "Stock agent"}</strong><VIconButton variant="ghost" className={styles.action} label={zh ? "收起功能栏" : "Collapse functions"} icon={<PanelLeftClose size={16} />} onPress={onCollapse} /></header>
    <nav className={styles.scroll} aria-label={zh ? "股票智能体功能" : "Stock agent functions"}>{FINANCE_WORKSPACE_GROUPS.map(group => {
      const Icon = icons[group.id];
      return <section key={group.id} className={styles.group}><div className={styles.groupHeading}><Icon size={13} /><span>{zh ? group.zh : group.en}</span></div>{group.areas.map(item => <VButton key={item.id} variant="ghost" className={[styles.link, item.id === area ? styles.selected : ""].join(" ")} aria-pressed={item.id === area} onPress={() => onNavigate(item.id)}>{zh ? item.zh : item.en}</VButton>)}</section>;
    })}</nav>
    <footer className={styles.footer}><div className={styles.identity}><Bot size={15} /><strong title={displayName}>{displayName}</strong></div><VRouteLinkButton variant="ghost" className={styles.config} to={configHref} icon={<Settings2 size={14} />} aria-label={zh ? "模型与助手配置" : "Assistant settings"} title={modelLabel || displayName}>{modelLabel || (zh ? "模型与助手配置" : "Assistant settings")}</VRouteLinkButton></footer>
  </div>;
}
