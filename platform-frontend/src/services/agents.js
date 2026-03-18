/**
 * agents.js
 * ---------
 * Agent Library API calls.
 * Drop this file into platform-frontend/src/services/
 * and import wherever needed.
 *
 * All functions use the same base URL convention as your existing api.js.
 */

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Fetch the full agent catalog.
 * @param {{ tier?: number, role?: string, tag?: string }} filters
 * @returns {Promise<{ agents: Agent[], count: number }>}
 */
export async function getAgentCatalog({ tier, role, tag } = {}) {
  const params = new URLSearchParams()
  if (tier !== undefined) params.set('tier', tier)
  if (role)               params.set('role', role)
  if (tag)                params.set('tag', tag)

  const query = params.toString() ? `?${params.toString()}` : ''
  const res   = await fetch(`${BASE_URL}/api/agents/${query}`)
  if (!res.ok) throw new Error(`Failed to fetch agent catalog: ${res.statusText}`)
  return res.json()
}

/**
 * Fetch a single agent by ID.
 * @param {string} agentId
 * @returns {Promise<Agent>}
 */
export async function getAgentById(agentId) {
  const res = await fetch(`${BASE_URL}/api/agents/${agentId}`)
  if (!res.ok) throw new Error(`Agent '${agentId}' not found`)
  return res.json()
}

/**
 * Record a user's agent selection for an AEG node.
 * @param {{ aegNodeId: string, agentId: string }} params
 * @returns {Promise<{ status: string, aeg_node_id: string, agent: Agent }>}
 */
export async function selectAgentForNode({ aegNodeId, agentId }) {
  const res = await fetch(`${BASE_URL}/api/agents/select`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ aeg_node_id: aegNodeId, agent_id: agentId }),
  })
  if (!res.ok) throw new Error(`Agent selection failed: ${res.statusText}`)
  return res.json()
}
