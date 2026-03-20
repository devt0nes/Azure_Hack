import axios from 'axios';
import { DirectorReply, BuildContext, AgentStatus } from './types';

const DIRECTOR_BASE_URL = 'http://localhost:8000';

export async function sendToClarify(projectId: string, userInput: string): Promise<DirectorReply> {
  try {
    const res = await axios.post<DirectorReply>(`${DIRECTOR_BASE_URL}/clarify`, {
      project_id: projectId,
      user_input: userInput,
    });
    return res.data;
  } catch {
    return {
      project_id: projectId,
      director_reply: `[MOCK] Got your request: "${userInput}". What database should this use? (PostgreSQL / MongoDB / SQLite)`,
      task_ledger_updated: false,
      state: 'CLARIFYING',
    };
  }
}

export async function getProjectStatus(projectId: string): Promise<{
  status: string;
  progress: number;
  error: string | null;
}> {
  try {
    const res = await axios.get(`${DIRECTOR_BASE_URL}/api/projects/${projectId}`);
    return {
      status: res.data.status,
      progress: res.data.progress,
      error: res.data.error,
    };
  } catch {
    return { status: 'unknown', progress: 0, error: null };
  }
}

export async function getAEGStatus(projectId: string): Promise<{
  agents: Array<{ id: string; agent_type: string; state: string }>;
  progress: number;
  status: string;
}> {
  try {
    const res = await axios.get(`${DIRECTOR_BASE_URL}/aeg?project_id=${projectId}`);
    const data = res.data;
    const agents = (data.task_ledger || []).map((task: any) => ({
      id: task.agent,
      agent_type: task.agent.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
      state: task.status === 'IN_PROGRESS' ? 'RUNNING' : task.status === 'COMPLETED' ? 'COMPLETED' : 'PENDING',
    }));
    return {
      agents,
      progress: data.progress || 0,
      status: data.status || 'UNKNOWN',
    };
  } catch {
    return { agents: [], progress: 0, status: 'UNKNOWN' };
  }
}

export async function getBuildContext(projectId: string): Promise<BuildContext> {
  try {
    const res = await axios.get<BuildContext>(`${DIRECTOR_BASE_URL}/context/${projectId}`);
    return res.data;
  } catch {
    return {
      project_id: projectId,
      task_ledger: { app_type: 'REST API', auth: 'JWT', database: 'PostgreSQL' },
      aeg: {
        nodes: [
          { id: 'backend', agent_type: 'BackendEngineer', state: 'COMPLETED' },
          { id: 'db', agent_type: 'DatabaseArchitect', state: 'RUNNING' },
          { id: 'devops', agent_type: 'DevOps', state: 'PENDING' },
        ],
        edges: [{ from: 'backend', to: 'db' }, { from: 'db', to: 'devops' }],
      },
      agents: [],
    };
  }
}

export async function getAgentLogs(agentId: string, projectId: string): Promise<AgentStatus> {
  try {
    const res = await axios.get<AgentStatus>(
      `${DIRECTOR_BASE_URL}/agents/${agentId}/logs?project_id=${projectId}`
    );
    return res.data;
  } catch {
    return {
      agent_id: agentId,
      state: 'FAILED',
      logs: [
        '[MOCK] Agent started successfully',
        '[MOCK] Generating schema...',
        '[MOCK] ERROR: Connection timeout to Azure SQL',
        '[MOCK] Retrying with Healer agent...',
      ],
      tokens_used: 1420,
      cost: 0.02,
      error: 'Azure SQL connection timeout after 3 retries',
    };
  }
}

export function generateProjectId(): string {
  return `proj_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

export function stateEmoji(state: string): string {
  const map: Record<string, string> = {
    PENDING: '⏳',
    RUNNING: '🔄',
    COMPLETED: '✅',
    FAILED: '❌',
    IN_PROGRESS: '🔄',
    DRAFT: '📝',
    DONE: '✅',
  };
  return map[state] ?? '❓';
}