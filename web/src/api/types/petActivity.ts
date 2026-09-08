export type PetActivityTone = "approval" | "error" | "running" | "completed" | "idle";

export type PetActivityPhase =
  | "waiting"
  | "error"
  | "thinking"
  | "reading"
  | "tooling"
  | "verifying"
  | "answering"
  | "completed";

export type PetAnimationState =
  | "idle"
  | "waiting"
  | "alert"
  | "thinking"
  | "reading"
  | "tooling"
  | "verifying"
  | "answering"
  | "celebrating";

export type PetActivitySession = {
  sessionId: string;
  title: string;
  agentId: string;
  agentDisplayName: string;
  tone: PetActivityTone;
  phase: PetActivityPhase;
  updatedAt: string;
};

export type PetActivity = {
  schemaVersion: 1;
  aggregateTone: PetActivityTone;
  animationState: PetAnimationState;
  activeCount: number;
  attentionCount: number;
  generatedAt: string;
  sessions: PetActivitySession[];
};
