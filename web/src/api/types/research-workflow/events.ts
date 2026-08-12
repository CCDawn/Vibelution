/** Formal WorkflowEventEnvelope (T6 frozen read surface). */

export type WorkflowEventEnvelope<
  TType extends string = string,
  TPayload extends Record<string, unknown> = Record<string, unknown>,
> = {
  eventId: string;
  sequence: number;
  runId: string;
  teamId: string;
  runVersion: number;
  type: TType;
  correlationId: string;
  causationId?: string;
  occurredAt: string;
  payload: TPayload;
};
