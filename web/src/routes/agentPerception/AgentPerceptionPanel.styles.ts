/**
 * The perception workspace keeps its inspector beside the active page on wide
 * screens and stacks it below the page on narrow screens. Width memory still
 * belongs to VSplitWorkspace's shared layout persistence.
 */
const styles = {
  workspace: [
    // Route styles can be prefetched later; keep their generic flex utilities
    // from changing this recipe's direction or its natural-height panes.
    "[&[data-vui=split-workspace]]:!flex-col !overflow-visible xl:[&[data-vui=split-workspace]]:!flex-row",
    "[&>[data-vui-layout-handle]]:hidden xl:[&>[data-vui-layout-handle]]:flex",
    "[&>main[data-vui=split-main]]:!h-auto [&>main[data-vui=split-main]]:!flex-none [&>main[data-vui=split-main]]:!overflow-visible",
    "xl:[&>main[data-vui=split-main]]:!flex-1",
    "[&>aside[data-vui=split-aside]]:!h-auto [&>aside[data-vui=split-aside]]:!w-full",
    "[&>aside[data-vui=split-aside]]:!basis-auto [&>aside[data-vui=split-aside]]:!min-w-0 [&>aside[data-vui=split-aside]]:!max-w-none [&>aside[data-vui=split-aside]]:!flex-none",
    "xl:[&>aside[data-vui=split-aside]]:!w-[var(--pane-w-runtime)]",
    "xl:[&>aside[data-vui=split-aside]]:!basis-[var(--pane-w-runtime)] xl:[&>aside[data-vui=split-aside]]:!min-w-[260px] xl:[&>aside[data-vui=split-aside]]:!max-w-[480px]",
  ].join(" "),
  mainContent: "mx-auto grid w-full max-w-5xl min-w-0 gap-3",
  runtimeAside: "grid min-w-0 gap-3 xl:min-h-0 xl:overflow-y-auto",
} as const;

export default styles;
