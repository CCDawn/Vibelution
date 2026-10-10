import { useRef, type ReactNode } from "react";
import { CircleCheck, CircleAlert, LoaderCircle, Users } from "lucide-react";
import { VButton } from "../../../src/components/vui";
import { getMember, members, type PreviewScene } from "./fixtures";

export const styles = {
  muted: "text-[var(--fg-tertiary)]",
  secondary: "text-[var(--fg-secondary)]",
  border: "border-[var(--vui-border-subtle)]",
  heading: "text-[15px] font-semibold tracking-normal text-[var(--fg-primary)]",
  quietButton: "!border-transparent !bg-transparent !shadow-none hover:!bg-[var(--vui-control-muted)]",
  touch: "!min-h-10 max-[600px]:!min-h-11",
  panel: "rounded-xl border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)]",
} as const;

export function usePreviewDialogFocus() {
  const returnTo = useRef<HTMLElement | null>(null);
  return {
    remember: () => {
      returnTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    },
    onCloseAutoFocus: (event: Event) => {
      if (returnTo.current?.isConnected) {
        event.preventDefault();
        returnTo.current.focus({ preventScroll: true });
      }
    },
  };
}

export function Avatar({ id, small = false }: { id: string; small?: boolean }) {
  const member = getMember(id);
  return <span aria-hidden="true" className={`${small ? "h-7 w-7 text-[11px]" : "h-9 w-9 text-[13px]"} ${id === "user" ? "bg-slate-100 text-slate-600" : member.color} inline-flex shrink-0 items-center justify-center rounded-xl font-semibold ring-1 ring-inset ring-black/5`}>{id === "user" ? "你" : member.initials}</span>;
}

export function SceneStatus({ scene }: { scene: PreviewScene }) {
  const config = scene === "error" ? { icon: CircleAlert, text: "需要处理", color: "text-amber-700 bg-amber-50" }
    : scene === "completed" ? { icon: CircleCheck, text: "已完成", color: "text-emerald-700 bg-emerald-50" }
    : scene === "empty" ? { icon: CircleCheck, text: "待开始", color: "text-slate-600 bg-slate-100" }
    : { icon: LoaderCircle, text: "评审中", color: "text-blue-700 bg-blue-50" };
  const Icon = config.icon;
  return <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${config.color}`}><Icon size={13} aria-hidden="true" />{config.text}</span>;
}

export function PageHeading({ title, subtitle, scene, onMembers, actions, status }: { title: string; subtitle: string; scene: PreviewScene; onMembers: () => void; actions?: ReactNode; status?: ReactNode }) {
  return <header className="flex min-w-0 shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-7 py-5 max-[600px]:px-4 max-[600px]:py-4">
    <div className="min-w-0"><p className="mb-1 text-xs text-[var(--fg-tertiary)]">{subtitle}</p><div className="flex flex-wrap items-center gap-3"><h1 className="m-0 text-[21px] font-semibold leading-tight tracking-normal max-[600px]:text-lg">{title}</h1>{status ?? <SceneStatus scene={scene} />}</div></div>
    <div className="flex shrink-0 items-center gap-2">{actions}<VButton icon={<Users size={16} />} variant="ghost" className={styles.touch} onClick={onMembers}>成员</VButton></div>
  </header>;
}

export function MemberList() {
  return <div className="grid gap-1">{members.map((member) => <div className="flex items-center gap-3 rounded-lg py-3" key={member.id}><Avatar id={member.id} /><div className="min-w-0 flex-1"><p className="text-sm font-semibold">{member.name}</p><p className="mt-0.5 text-xs text-[var(--fg-tertiary)]">{member.role}</p></div><span className="text-xs text-[var(--fg-tertiary)]">{member.model}</span></div>)}</div>;
}
