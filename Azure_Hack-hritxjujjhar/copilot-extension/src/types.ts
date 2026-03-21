export interface DirectorReply {
  project_id: string;
  director_reply: string;
  task_ledger_updated: boolean;
  state: 'CLARIFYING' | 'BUILDING' | 'DONE' | 'ERROR';
}

export interface AgentStatus {
  agent_id: string;
  state: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  logs: string[];
  tokens_used: number;
  cost: number;
  error?: string;
}

export interface BuildContext {
  project_id: string;
  task_ledger: Record<string, unknown>;
  aeg: { nodes: unknown[]; edges: unknown[] };
  agents: AgentStatus[];
}