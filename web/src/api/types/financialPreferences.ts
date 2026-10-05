export type FinancialPreference = { id: string; text: string; createdAt: string };
export type FinancialPreferences = { agentId: string; memoryEnabled: boolean; items: FinancialPreference[]; limit: number };
