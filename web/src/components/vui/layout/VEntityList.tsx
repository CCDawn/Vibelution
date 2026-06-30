import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VEntityListItem = {
  id: string | number;
};

export type VEntityListProps<TItem extends VEntityListItem> = Omit<
  ComponentPropsWithoutRef<"div">,
  "children"
> & {
  activeId?: TItem["id"];
  ariaLabel: string;
  empty?: ReactNode;
  items: TItem[];
  renderItem: (item: TItem, index: number) => ReactNode;
};

export function VEntityList<TItem extends VEntityListItem>({
  activeId,
  ariaLabel,
  className,
  empty,
  items,
  renderItem,
  ...props
}: VEntityListProps<TItem>) {
  return (
    <div
      {...props}
      data-vui="entity-list"
      role="list"
      aria-label={ariaLabel}
      className={[
        "grid min-w-0 content-start gap-1 rounded-md border border-vui-border-subtle",
        "bg-vui-surface-glass p-1 backdrop-blur-md",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {items.length === 0 ? (
        <div data-vui="entity-list-empty" className="px-2 py-3 text-sm text-vui-fg-tertiary">
          {empty ?? "No items"}
        </div>
      ) : (
        items.map((item, index) => (
          <div
            key={item.id}
            data-active={activeId === item.id ? "true" : undefined}
            data-vui="entity-list-item"
            role="listitem"
            className={[
              "min-w-0 rounded-md border border-transparent px-2 py-1.5 text-sm",
              "text-vui-fg-secondary transition-colors",
              activeId === item.id
                ? "border-vui-accent-cool bg-[var(--vui-status-info-bg)] text-vui-fg-primary"
                : "hover:border-vui-border-subtle hover:bg-vui-control-muted",
            ].join(" ")}
          >
            {renderItem(item, index)}
          </div>
        ))
      )}
    </div>
  );
}
