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

export const clarify = ({ projectId, userInput }) =>
  apiFetch('/clarify', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, user_input: userInput }),
  })

export const clarifyWithAnswers = ({ projectId, userInput, answers }) =>
  apiFetch('/clarify', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, user_input: userInput, answers }),
  })

export const getAEG = ({ projectId }) =>
  apiFetch(`/aeg?project_id=${projectId}`)

export const executeProject = ({ projectId }) =>
  apiFetch('/execute', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  })

export const deployProject = ({ projectId, mockSuccess = false }) =>
  apiFetch(`/api/projects/${projectId}/deploy`, {
    method: 'POST',
    body: JSON.stringify({
      project_id: projectId,
      enable_docker_build: true,
      enable_infrastructure: true,
      enable_cicd: true,
      mock_success: mockSuccess,
    }),
  })

export const getDeploymentStatus = ({ projectId }) =>
  apiFetch(`/api/projects/${projectId}/deployment-status`)

export const getHealth = () => apiFetch('/api/health')
export const listProjects = () => apiFetch('/api/projects')
export const getProject = ({ projectId }) => apiFetch(`/api/projects/${projectId}`)
export const getProjectPreviewStatus = ({ projectId }) => apiFetch(`/api/projects/${projectId}/preview-status`)
export const getProjectLogs = ({ projectId }) => apiFetch(`/api/projects/${projectId}/logs`)
export const getProjectAgentEvents = ({ projectId }) => apiFetch(`/api/projects/${projectId}/agent-events`)