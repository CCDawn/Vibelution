import { Check, ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { VButton, VDropdownMenu } from "../components/vui";

export function specialistAgentSection(pathname: string): "finance" | "companions" | "" {
  if (pathname === "/finance" || pathname.startsWith("/finance/")) return "finance";
  if (pathname === "/companions" || pathname.startsWith("/companions/")) return "companions";
  return "";
}

export function SpecialistAgentMenu({ lang, enabled, className, activeClassName, onNavigate, onOpenFinance }: {
  lang: "zh" | "en"; enabled: boolean; className: string; activeClassName: string;
  onNavigate: (to: string) => void;
  onOpenFinance: () => void;
}) {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const section = specialistAgentSection(location.pathname);
  useEffect(() => { setOpen(false); }, [location.pathname, location.search, location.key]);
  const choose = (to: string) => { setOpen(false); onNavigate(to); };
  const openFinance = () => { setOpen(false); onOpenFinance(); };
  const title = lang === "zh" ? "智能体" : "Specialist agents";
  return <VDropdownMenu
    open={open} onOpenChange={setOpen} side="bottom" align="start" aria-label={title}
    trigger={<VButton type="button" variant="ghost" isDisabled={!enabled}
      className={section ? activeClassName : className} aria-current={section ? "page" : undefined}
      data-agent-section={section} trailingIcon={<ChevronDown size={13} aria-hidden="true" />}>
      {title}
    </VButton>}
    items={[
      { id: "finance", label: lang === "zh" ? "炒股智能体" : "Investment assistant",
        icon: section === "finance" ? <Check size={14} /> : undefined, onSelect: openFinance },
      { id: "companions", label: lang === "zh" ? "虚拟人智能体" : "Virtual-human companions",
        icon: section === "companions" ? <Check size={14} /> : undefined, onSelect: () => choose("/companions") },
    ]}
  />;
}
