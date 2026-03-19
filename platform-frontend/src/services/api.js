const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

function requireApiBaseUrl() {
  if (!API_BASE_URL) {
    throw new Error('VITE_API_BASE_URL is not configured')
  }
}

export async function clarify({ projectId, userInput }) {
  requireApiBaseUrl()
  const response = await fetch(`${API_BASE_URL}/clarify`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      project_id: projectId,
      user_input: userInput,
    }),
  })

  if (!response.ok) {
    throw new Error('Director request failed')
  }

  return response.json()
}

export async function getAEG({ projectId }) {
  requireApiBaseUrl()
  const response = await fetch(`${API_BASE_URL}/aeg?project_id=${projectId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error('Failed to fetch AEG')
  }

  return response.json()
}

export async function executeProject({ projectId }) {
  requireApiBaseUrl()
  const response = await fetch(`${API_BASE_URL}/execute`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      project_id: projectId,
    }),
  })

  if (!response.ok) {
    throw new Error('Failed to start execution')
  }

  return response.json()
}

export async function getHealth() {
  requireApiBaseUrl()
  const response = await fetch(`${API_BASE_URL}/api/health`)

  if (!response.ok) {
    throw new Error('Health check failed')
  }

  return response.json()
}

export async function listProjects() {
  requireApiBaseUrl()
  const response = await fetch(`${API_BASE_URL}/api/projects`)

  if (!response.ok) {
    throw new Error('Failed to list projects')
  }

  return response.json()
}

export async function getProject({ projectId }) {
  requireApiBaseUrl()
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}`)

  if (!response.ok) {
    throw new Error('Failed to fetch project')
  }

  return response.json()
}

export async function getProjectLogs({ projectId }) {
  requireApiBaseUrl()
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/logs`)

  if (!response.ok) {
    throw new Error('Failed to fetch project logs')
  }

  return response.json()
}
