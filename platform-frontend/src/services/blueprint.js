const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export async function getBuildContext({ projectId }) {
  try {
    const response = await fetch(`${API_BASE_URL}/context/${projectId}`)
    if (!response.ok) throw new Error('Failed to fetch context')
    return response.json()
  } catch {
    return {
      project_id: projectId,
      task_ledger: {
        app_type: 'REST API',
        auth: 'JWT',
        database: 'PostgreSQL',
        framework: 'FastAPI',
      },
      aeg: {
        nodes: [
          { id: 'backend', agent_type: 'BackendEngineer', state: 'COMPLETED' },
          { id: 'db', agent_type: 'DatabaseArchitect', state: 'COMPLETED' },
          { id: 'devops', agent_type: 'DevOps', state: 'COMPLETED' },
          { id: 'qa', agent_type: 'QAEngineer', state: 'COMPLETED' },
        ],
        edges: [
          { from: 'backend', to: 'db' },
          { from: 'db', to: 'devops' },
          { from: 'devops', to: 'qa' },
        ],
      },
      agents: [
        { id: 'backend', tokens_used: 1250, cost: 0.031, state: 'COMPLETED' },
        { id: 'db', tokens_used: 890, cost: 0.022, state: 'COMPLETED' },
        { id: 'devops', tokens_used: 640, cost: 0.016, state: 'COMPLETED' },
        { id: 'qa', tokens_used: 420, cost: 0.011, state: 'COMPLETED' },
      ],
    }
  }
}

export function generateBlueprint({ projectId, context }) {
  return {
    blueprint_version: '1.0',
    generated_at: new Date().toISOString(),
    project_id: projectId,
    task_ledger: context.task_ledger,
    aeg: context.aeg,
    agents: context.agents,
    summary: {
      total_agents: context.agents.length,
      total_tokens: context.agents.reduce((sum, a) => sum + (a.tokens_used || 0), 0),
      total_cost: context.agents.reduce((sum, a) => sum + (a.cost || 0), 0).toFixed(4),
    },
  }
}

export function downloadBlueprint({ blueprint, projectId }) {
  const json = JSON.stringify(blueprint, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `blueprint-${projectId}-${Date.now()}.json`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}