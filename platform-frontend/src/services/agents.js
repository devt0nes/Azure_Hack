/**
 * services/agents.js
 * ------------------
 * API service layer for the Agent Catalog / Marketplace.
 * All calls go through VITE_API_BASE_URL (same as api.js).
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

// ── Fetch full catalog ────────────────────────────────────────────────────────
export async function getAgentCatalog({ tier, role, tag } = {}) {
  const params = new URLSearchParams()
  if (tier !== undefined) params.set('tier', tier)
  if (role)              params.set('role', role)
  if (tag)               params.set('tag',  tag)

  const qs  = params.toString()
  const url = `${API_BASE_URL}/api/agents${qs ? '?' + qs : ''}`
  const res = await fetch(url)
  if (!res.ok) throw new Error('Failed to fetch agent catalog')
  return res.json()   // { agents, count, source }
}

// ── Fetch a single agent ─────────────────────────────────────────────────────
export async function getAgent(agentId) {
  const res = await fetch(`${API_BASE_URL}/api/agents/${agentId}`)
  if (!res.ok) throw new Error(`Agent '${agentId}' not found`)
  return res.json()
}

// ── Fetch agents already selected for a project ──────────────────────────────
export async function getSelectedAgents(projectId) {
  if (!projectId) return { selected_agents: [], count: 0 }
  const res = await fetch(`${API_BASE_URL}/api/agents/selected/${projectId}`)
  if (!res.ok) throw new Error('Failed to fetch selected agents')
  return res.json()   // { project_id, selected_agents, count }
}

// ── Record a selection (called when user clicks "+ Add") ─────────────────────
export async function selectAgentForNode({ aegNodeId, agentId, projectId }) {
  const res = await fetch(`${API_BASE_URL}/api/agents/select`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      aeg_node_id: aegNodeId  || 'unassigned',
      agent_id:    agentId,
      project_id:  projectId  || null,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to select agent')
  }
  return res.json()   // { status, aeg_node_id, agent }
}

export async function deselectAgentForProject({ projectId, agentId }) {
  if (!projectId) throw new Error('projectId is required to deselect an agent')
  if (!agentId) throw new Error('agentId is required to deselect an agent')

  const res = await fetch(`${API_BASE_URL}/api/agents/select/${projectId}/${agentId}`, {
    method: 'DELETE',
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to deselect agent')
  }

  return res.json()
}
