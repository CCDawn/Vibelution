import { VStatusChip, VTooltip } from "../../../components/vui";
import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import css from "./ChallengeCupExperimentProtocol.module.css";

type ChallengeProjection = NonNullable<ExperimentPlanningStatusPayload["challengeProgramProjection"]>;

type ChallengeCupExperimentProtocolProps = {
  stage1: ChallengeProjection["stage1ComplianceReadiness"];
  stage2?: ChallengeProjection["stage2BatchGovernance"];
};

type ProtocolGate = {
  detail: string;
  label: string;
  ready: boolean;
};

export function ChallengeCupExperimentProtocol({
  stage1,
  stage2,
}: ChallengeCupExperimentProtocolProps) {
  const gates: ProtocolGate[] = [
    {
      label: "研究计划",
      ready: stage1.acceptance.researchPlanPresent,
      detail: stage1.acceptance.researchPlanPresent ? "研究计划已登记" : "等待研究计划登记",
    },
    {
      label: "评审门",
      ready: stage1.acceptance.allSevenDimensionsReviewed,
      detail: stage1.acceptance.allSevenDimensionsReviewed ? "七维评审已完成" : "等待七维评审完成",
    },
    {
      label: "账本",
      ready: Boolean(stage2?.ledger.initialized && stage2.ledger.manifestHashVerified && stage2.ledger.citationAuditComplete),
      detail: stage2?.completionDefinition || "等待批处理账本初始化",
    },
  ];

  return (
    <section className={css.protocol} aria-labelledby="challenge-experiment-protocol-title">
      <header className={css.header}>
        <h3 id="challenge-experiment-protocol-title">实验协议</h3>
      </header>
      <div className={css.gates} aria-label="实验协议门禁">
        {gates.map((gate) => (
          <VTooltip content={gate.detail} key={gate.label}>
            <dl className={css.gate}>
              <dt>{gate.label}</dt>
              <dd>
                <VStatusChip tone={gate.ready ? "accent" : "neutral"}>
                  {gate.ready ? "已就绪" : "待完成"}
                </VStatusChip>
              </dd>
            </dl>
          </VTooltip>
        ))}
      </div>
    </section>
  );
}
