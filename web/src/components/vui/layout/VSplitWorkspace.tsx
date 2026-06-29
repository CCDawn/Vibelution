import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VSplitWorkspaceProps = Omit<ComponentPropsWithoutRef<"div">, "children"> & {
  aside?: ReactNode;
  main: ReactNode;
  sidebar?: ReactNode;
};

export function VSplitWorkspace({
  aside,
  className,
  main,
  sidebar,
  ...props
}: VSplitWorkspaceProps) {
  const columns = aside
    ? "grid-cols-[minmax(0,var(--vui-workspace-sidebar))_minmax(0,1fr)_minmax(0,var(--vui-workspace-aside))]"
    : sidebar
      ? "grid-cols-[minmax(0,var(--vui-workspace-sidebar))_minmax(0,1fr)]"
      : "grid-cols-[minmax(0,1fr)]";

  return (
    <div
      {...props}
      data-vui="split-workspace"
      className={["grid min-h-0 min-w-0 gap-2", columns, className]
        .filter(Boolean)
        .join(" ")}
    >
      {sidebar ? (
        <aside data-vui="split-sidebar" className="min-h-0 min-w-0">
          {sidebar}
        </aside>
      ) : null}
      <main data-vui="split-main" className="min-h-0 min-w-0">
        {main}
      </main>
      {aside ? (
        <aside data-vui="split-aside" className="min-h-0 min-w-0">
          {aside}
        </aside>
      ) : null}
    </div>
  );
}
