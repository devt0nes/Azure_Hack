import { getToken } from '../firebaseConfig'

// Fall back to localhost so the marketplace works even without a .env file
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// ─── Public fetch (no auth) — used for read-only catalog endpoints ───────────
async function publicFetch(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
  if (!response.ok) throw new Error(`Request failed: ${path} (${response.status})`)
  return response.json()
}

// ─── Authenticated fetch — used for write operations ────────────────────────
async function apiFetch(path, options = {}) {
  const token = await getToken()   // always fresh; Firebase handles refresh

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...options.headers,
    },
  })

  if (response.status === 401) {
    throw new Error('Unauthorized — please log in again')
  }
  if (!response.ok) throw new Error(`Request failed: ${path} (${response.status})`)
  return response.json()
}

/**
 * Get the full agent catalog with optional filtering.
 * Uses unauthenticated fetch — catalog is public read-only data.
 * @param {Object} params
 * @param {number} params.tier  - Optional tier filter (1 or 2)
 * @param {string} params.role  - Optional role filter
 * @param {string} params.tag   - Optional tag filter
 * @returns {Promise<Object>} { agents: [...], count: number, source: string }
 */
export const getAgentCatalog = ({ tier, role, tag } = {}) => {
  const query = new URLSearchParams()
  if (tier !== undefined) query.append('tier', tier)
  if (role !== undefined) query.append('role', role)
  if (tag !== undefined) query.append('tag', tag)

  const queryString = query.toString()
  const path = `/api/agents${queryString ? `?${queryString}` : ''}`
  return publicFetch(path)
}

/**
 * Get a single agent by ID (unauthenticated).
 * @param {string} agentId
 * @returns {Promise<Object>} Agent document
 */
export const getAgent = (agentId) =>
  publicFetch(`/api/agents/${agentId}`)

/**
 * Select an agent for a specific AEG node in a project.
 * Accepts both snake_case and camelCase callers because the hrit marketplace
 * uses camelCase while older code in this branch used snake_case.
 */
export const selectAgentForNode = ({
  aeg_node_id,
  aegNodeId,
  agent_id,
  agentId,
  project_id,
  projectId,
}) =>
  apiFetch('/api/agents/select', {
    method: 'POST',
    body: JSON.stringify({
      aeg_node_id: aeg_node_id ?? aegNodeId,
      agent_id: agent_id ?? agentId,
      project_id: project_id ?? projectId ?? null,
    }),
  })

/**
 * Deselect an agent from a project.
 * Accepts either `(projectId, agentId)` or `{ projectId, agentId }`.
 */
export const deselectAgent = (projectArg, agentArg) => {
  const projectId =
    typeof projectArg === 'object' && projectArg !== null ? projectArg.projectId : projectArg
  const agentId =
    typeof projectArg === 'object' && projectArg !== null ? projectArg.agentId : agentArg

  return apiFetch(`/api/agents/select/${projectId}/${agentId}`, {
    method: 'DELETE',
  })
}

// Alias for compatibility with existing components
export const deselectAgentForProject = deselectAgent

/**
 * Get selected agents for a specific project
 * @param {string} projectId - The project ID
 * @returns {Promise<Object>} { project_id: string, selected_agents: [...], count: number }
 */
export const getSelectedAgents = (projectId) =>
  apiFetch(`/api/agents/selected/${projectId}`)

/**
 * Create a new custom agent and persist it to CosmosDB.
 * @param {{ role: string, description: string, tier: number, tags: string[], model_label?: string }} agentData
 * @returns {Promise<{ ok: boolean, agent: Object }>}
 */
export const createCustomAgent = (agentData) =>
  publicFetch('/api/agents', {
    method: 'POST',
    body: JSON.stringify(agentData),
  })
