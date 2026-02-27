const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export async function clarify({ projectId, userInput }) {
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
