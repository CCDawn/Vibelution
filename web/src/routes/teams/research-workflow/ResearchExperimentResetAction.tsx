import { useState } from "react";

import { VButton, VDropdownMenu } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { ChallengeQuestionRunResetDialog } from "../challenge-cup/ChallengeQuestionRunResetDialog";

export function ResearchExperimentResetAction(props: {
  teamId: string;
  questionId: string;
  onCompleted: (targetNodeId: string) => void;
}) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      <VDropdownMenu
        aria-label={isZh ? "实验更多操作" : "More experiment actions"}
        align="end"
        items={[
          {
            id: "reset-experiment-run",
            label: isZh ? "重置本题运行" : "Reset this question run",
            danger: true,
            onSelect: () => setDialogOpen(true),
          },
        ]}
        trigger={(
          <VButton type="button" density="compact" variant="secondary">
            {isZh ? "更多操作" : "More actions"}
          </VButton>
        )}
      />
      <ChallengeQuestionRunResetDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        teamId={props.teamId}
        questionId={props.questionId}
        onCompleted={props.onCompleted}
      />
    </>
  );
}
