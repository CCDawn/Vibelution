/**
 * VSettingsRow / VSettingsGroupCard —— 预览本地行原语（正式 designs 登记留给集成任务）。
 *
 * 对照 ZCode packages/ui/src/settings/SettingsPageParts.tsx 的 SettingsRow：
 * - label（--vui-font-sm 加重）+ 一行说明（xs 弱色）在左；
 * - 右侧定宽控件列：默认 192px，宽控件 280px；宽控件时 detail 并列在控件左侧，
 *   否则 detail 换行渲染在行下方；
 * - 行间 border-t 分隔（--vui-border-subtle），组容器=圆角边框卡、无阴影
 *   （对照 SettingsGroupCard）。
 * 本组件只做布局壳，不引第二设计系统；全部样式走 --vui-* 令牌阶梯。
 */
import type { ReactNode } from "react";

export type VSettingsRowProps = {
  /** 行主标题（--vui-font-sm）。 */
  label: ReactNode;
  /** 一行说明（xs 弱色）。 */
  description?: ReactNode;
  /** 右侧控件（查看态=只读值展示，编辑态=控件）。 */
  control?: ReactNode;
  /** 附属内容：宽控件时并列在控件左；普通控件时换行渲染在行下方。 */
  detail?: ReactNode;
  /** 始终渲染在整行下方的块（宽控件内联错误、list/json 编辑器等）。 */
  footer?: ReactNode;
  /** 宽控件布局（280px 列），用于 number 步进器等。 */
  controlLayout?: "default" | "wide";
  /** 行右侧状态徽标（clean 时不渲染）。 */
  status?: ReactNode;
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
  testId,
}: VSettingsRowProps) {
  return (
    <div
      data-testid={testId}
      data-vui-settings-row=""
      className="border-t border-vui-border-subtle px-4 py-3 first:border-t-0"
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
export function VSettingsGroupCard({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div
      data-testid={testId}
      data-vui-settings-group=""
      className="overflow-hidden rounded-vui-panel border border-vui-border-subtle bg-vui-surface-card"
    >
      {children}
    </div>
  );
}
