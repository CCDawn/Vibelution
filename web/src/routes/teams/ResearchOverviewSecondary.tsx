import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import { VNativeButton, VSurface } from "../../components/vui";

/**
 * GitHub "Details" / Linear "More" pattern: one quiet disclosure row, no fake dual CTAs.
 */
export type ResearchOverviewSecondaryProps = {
  lang: "zh" | "en";
  children: ReactNode;
  defaultOpen?: boolean;
};

export function ResearchOverviewSecondary({
  lang,
  children,
  defaultOpen = false,
}: ResearchOverviewSecondaryProps) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  const label = lang === "zh" ? "高级详情" : "Advanced details";

  return (
    <VSurface
      tone="row"
      elevation="flat"
      padding="none"
      className="min-w-0 overflow-hidden rounded-lg border border-[var(--vui-border-subtle)]"
      data-testid="research-overview-secondary"
    >
      <VNativeButton
        type="button"
        className={[
          "!flex h-9 w-full !items-center !justify-start gap-2 !rounded-none !border-0 !bg-transparent px-3 text-left",
          "!text-[13px] !font-medium !text-[var(--fg-secondary)]",
          "hover:!bg-[color-mix(in_srgb,var(--vui-control-muted)_55%,transparent)]",
        ].join(" ")}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronDown
          size={14}
          aria-hidden="true"
          className={[
            "shrink-0 text-[var(--fg-tertiary)] transition-transform duration-150",
            open ? "rotate-0" : "-rotate-90",
          ].join(" ")}
        />
        <span className="min-w-0 flex-1 truncate text-[var(--fg-primary)]">{label}</span>
        <span className="shrink-0 text-[11px] font-normal text-[var(--fg-tertiary)]">
          {open
            ? (lang === "zh" ? "收起" : "Hide")
            : (lang === "zh" ? "证据与校验" : "Evidence & checks")}
        </span>
      </VNativeButton>
      {open ? (
        <div
          id={panelId}
          className="grid min-w-0 gap-2 border-t border-[var(--vui-border-subtle)] p-3"
        >
          {children}
        </div>
      ) : null}
    </VSurface>
  );
}
