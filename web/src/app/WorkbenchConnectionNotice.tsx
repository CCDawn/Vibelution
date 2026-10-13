import { VButton, VStateSurface } from "../components/vui";

type Props = {
  unavailable: boolean;
  lang: string;
  desktopShell: boolean;
  recovering: boolean;
  onRecover: () => void;
  onRetry: () => void;
};

/** Health failure is a connection observation, not proof that the service stopped. */
export function WorkbenchConnectionNotice({ unavailable, lang, desktopShell, recovering, onRecover, onRetry }: Props) {
  if (!unavailable) return null;
  const zh = lang !== "en";
  return (
    <VStateSurface
      data-testid="workbench-connection-notice"
      tone="unavailable"
      className="shrink-0 rounded-none border-x-0 border-t-0 px-3 py-2"
      role="status"
      aria-live="polite"
      title={zh ? "工作台服务未连接" : "Workbench service disconnected"}
      actions={<div className="flex flex-wrap items-center gap-2">
        {desktopShell ? <VButton variant="secondary" density="compact" isDisabled={recovering} isPending={recovering} onPress={onRecover}>
          {recovering ? (zh ? "正在恢复工作台" : "Recovering workbench") : (zh ? "恢复工作台" : "Recover workbench")}
        </VButton> : null}
        <VButton variant="ghost" density="compact" isDisabled={recovering} onPress={onRetry}>{zh ? "检查连接" : "Check connection"}</VButton>
      </div>}
    >
      <span className="block">{zh ? "当前内容暂不可更新，已打开的内容和草稿仍保留。" : "Content cannot update right now. Open content and drafts are retained."}</span>
      <span className="block">{desktopShell
        ? (zh ? "恢复将通过启动管理重启服务；如有运行中的任务，会先停止任务并保存已有记录。" : "Recovery restarts the service through the Launcher, stopping active tasks and saving existing records first.")
        : (zh ? "请从 Vibelution 启动管理恢复工作台，再检查连接。" : "Recover the workbench from Vibelution Launcher, then check the connection.")}</span>
    </VStateSurface>
  );
}
