import { Moon, Sun } from "lucide-react";

import { VIconButton } from "../../components/vui";

export type VuiPreviewHeaderProps = {
  theme: "dark" | "light";
  onToggleTheme: () => void;
};

export function VuiPreviewHeader({ theme, onToggleTheme }: VuiPreviewHeaderProps) {
  return (
    <header className="flex min-w-0 items-center justify-between gap-3">
      <h1 className="m-0 text-[1.35rem] font-semibold tracking-[-0.035em] text-vui-fg-primary">VUI</h1>
      <VIconButton
        label={theme === "light" ? "切换深色" : "切换浅色"}
        icon={theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
        onPress={onToggleTheme}
      />
    </header>
  );
}
