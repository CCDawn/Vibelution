/**
 * VSettingsRow / VSettingsGroupCard —— 设置面行原语（ZCode SettingsRow 对齐）。
 *
 * - label（--vui-font-sm 加重）+ 一行说明（xs 弱色）在左；
 * - 右侧定宽控件列：默认 192px，宽控件（controlLayout="wide"）280px；宽控件时
 *   detail 并列在控件左侧，否则 detail 换行渲染在行下方；
 * - 行间 border-t 分隔（--vui-border-subtle），组容器=圆角边框卡、无阴影
 *   （VSettingsGroupCard）。
 * 本组件只做布局壳，不引第二设计系统；全部样式走 --vui-* 令牌阶梯。
 */
import type { ReactNode } from "react";

export type VSettingsRowProps = {
  /** 行主标题（--vui-font-sm）。 */
  label: ReactNode;
  /** 一行说明（xs 弱色）。 */
  description?: ReactNode;
  /** 右侧控件（查看态=只读值展示或即时类活控件，编辑态=控件）。 */
  control?: ReactNode;
  /** 附属内容：宽控件时并列在控件左；普通控件时换行渲染在行下方。 */
  detail?: ReactNode;
  /** 始终渲染在整行下方的块（宽编辑器、list/json 编辑器等）。 */
  footer?: ReactNode;
  /** 宽控件布局（280px 列），用于 number 步进器等。 */
  controlLayout?: "default" | "wide";
  /** 行右侧状态徽标（clean 时不渲染）。 */
  status?: ReactNode;
  /**
   * 瞬态高亮环（搜索深链落点等短暂定位）：accent-cool ring，约 2s 后由调用方
   * 摘除；只做视觉强调，不改变行布局与交互。
   */
  highlighted?: boolean;
  /** 供测试定位。 */
  testId?: string;
};

export function VSettingsRow({
  label,
  description,
  control,
  detail,
  footer,
  controlLayout = "default",
  status,
  highlighted = false,
  testId,
}: VSettingsRowProps) {
  return (
    <div
      data-testid={testId}
      data-vui="settings-row"
      data-vui-highlighted={highlighted ? "true" : undefined}
      className={
        [
          "border-t border-vui-border-subtle px-4 py-3 first:border-t-0",
          highlighted
            ? "rounded-vui-control ring-2 ring-[color-mix(in_srgb,var(--accent-cool)_45%,transparent)] ring-offset-1 ring-offset-[var(--vui-surface-panel)] transition-shadow"
            : "",
        ]
          .filter(Boolean)
          .join(" ")
      }
    >
      <div
        className={
          controlLayout === "wide"
            ? "grid grid-cols-[minmax(0,1fr)_280px] items-center gap-4"
            : "grid grid-cols-[minmax(0,1fr)_192px] items-center gap-4"
        }
      >
        <div className="min-w-0">
          <div className="text-vui-sm font-medium text-vui-fg-primary">{label}</div>
          {description ? (
            <div className="mt-1 text-vui-xs leading-5 text-vui-fg-tertiary">{description}</div>
          ) : null}
        </div>
        <div className="flex w-full flex-nowrap items-center justify-end gap-2">
          {status}
          {controlLayout === "wide" ? detail : null}
          {control}
        </div>
      </div>
      {detail && controlLayout !== "wide" ? <div className="mt-3">{detail}</div> : null}
      {footer ? <div className="mt-3">{footer}</div> : null}
    </div>
  );
}

/** 组容器：圆角边框卡、无阴影（对照 ZCode SettingsGroupCard）。 */
export function VSettingsGroupCard({
  children,
  testId,
  className,
}: {
  children: ReactNode;
  testId?: string;
  className?: string;
}) {
  return (
    <div
      data-testid={testId}
      data-vui="settings-group"
      className={["overflow-hidden rounded-vui-panel border border-vui-border-subtle bg-vui-surface-card", className]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </div>
  );
}
