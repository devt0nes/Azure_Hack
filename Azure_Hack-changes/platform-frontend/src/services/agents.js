import { getToken } from '../firebaseConfig'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

function requireApiBaseUrl() {
  if (!API_BASE_URL) throw new Error('VITE_API_BASE_URL is not configured')
}

async function apiFetch(path, options = {}) {
  requireApiBaseUrl()
  const token = await getToken()  // always fresh, Firebase handles refresh

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...options.headers,
    },
  })

  if (response.status === 401) {
    window.location.href = '/'
  }
  if (!response.ok) throw new Error(`Request failed: ${path}`)
  return response.json()
}

/**
 * Get the full agent catalog with optional filtering
 * @param {Object} params - Query parameters
 * @param {number} params.tier - Optional tier to filter by (1 or 2)
 * @param {string} params.role - Optional role to filter by
 * @param {string} params.tag - Optional tag to filter by
 * @returns {Promise<Object>} { agents: [...], count: number, source: string }
 */
export const getAgentCatalog = ({ tier, role, tag } = {}) => {
  const query = new URLSearchParams()
  if (tier !== undefined) query.append('tier', tier)
  if (role !== undefined) query.append('role', role)
  if (tag !== undefined) query.append('tag', tag)

  const queryString = query.toString()
  const path = `/api/agents${queryString ? `?${queryString}` : ''}`
  return apiFetch(path)
}

/**
 * Get a single agent by ID
 * @param {string} agentId - The agent ID
 * @returns {Promise<Object>} Agent document
 */
export const getAgent = (agentId) =>
  apiFetch(`/api/agents/${agentId}`)

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
