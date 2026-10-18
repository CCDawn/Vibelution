/** Personal-affairs plugin DTOs; value domains are backend closed enums. */
export type PersonalAffairKind = "todo" | "schedule" | "goal";

export type PersonalAffairStatus = "open" | "done" | "cancelled";

export type PersonalAffairDueState = "overdue" | "today" | "upcoming" | "none";

export type PersonalAffairItem = {
  schemaVersion: number;
  itemId: string;
  kind: PersonalAffairKind;
  title: string;
  note: string;
  status: PersonalAffairStatus;
  dueAt: string;
  createdAt: string;
  updatedAt: string;
  completedAt: string;
  sourceTurnId: string;
  dueState: PersonalAffairDueState;
};

export type PersonalAffairCounts = {
  open: number;
  overdue: number;
  done: number;
};

export type PersonalAffairList = {
  schemaVersion: number;
  agentId: string;
  items: PersonalAffairItem[];
  counts: PersonalAffairCounts;
  updatedAt: string;
};

export type PersonalAffairAddRequest = {
  kind: PersonalAffairKind;
  title: string;
  note?: string;
  dueAt?: string;
  sourceTurnId?: string;
};

export type PersonalAffairMutationResponse = {
  agentId: string;
  item: PersonalAffairItem;
};
