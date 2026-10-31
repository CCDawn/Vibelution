import { ShadcnComposerApprovalCard } from "../renderers/shadcn/ShadcnComposerApprovalCard";

export type VComposerApprovalCardProps = {
  lang: "zh" | "en";
  title: string;
  description: string;
  fullPreview: string;
  risk: string;
  scope: string;
  pending: boolean;
  approveDisabled: boolean;
  rejectDisabled: boolean;
  onApprove: () => void;
  onReject: () => void;
};

/** Non-modal, one-time decision adjacent to a conversation composer. */
export function VComposerApprovalCard(props: VComposerApprovalCardProps) {
  return <ShadcnComposerApprovalCard {...props} />;
}
