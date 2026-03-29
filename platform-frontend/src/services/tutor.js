const TUTOR_API_URL = import.meta.env.VITE_TUTOR_API_URL || import.meta.env.VITE_API_BASE_URL || ''
const TUTOR_API_KEY = import.meta.env.VITE_TUTOR_API_KEY || ''

function _headers() {
  return {
    'Content-Type': 'application/json',
    ...(TUTOR_API_KEY && { Authorization: `Bearer ${TUTOR_API_KEY}` }),
  }
}

function _assertUrl() {
  if (!TUTOR_API_URL) throw new Error('Tutor API URL is not configured')
}

export async function sessionStart({ projectId, depthLevel = 'beginner' }) {
  _assertUrl()
  const response = await fetch(`${TUTOR_API_URL}/tutor/session_start`, {
    method: 'POST',
    headers: _headers(),
    body: JSON.stringify({ project_id: projectId, depth_level: depthLevel }),
  })
  if (!response.ok) throw new Error(`Session start failed: ${response.status}`)
  return response.json()
}

export async function askTutor({ projectId, question, depthLevel = 'beginner', sessionHistory = [], context = {} }) {
  _assertUrl()
  const response = await fetch(`${TUTOR_API_URL}/tutor/ask`, {
    method: 'POST',
    headers: _headers(),
    body: JSON.stringify({
      project_id: projectId,
      question,
      depth_level: depthLevel,
      session_history: sessionHistory,
      context,
    }),
  })
  if (!response.ok) throw new Error(`Tutor request failed: ${response.status}`)
  return response.json()
}

export async function saveTour({ projectId, tourName, messages = [], depthLevel = 'beginner' }) {
  _assertUrl()
  const response = await fetch(`${TUTOR_API_URL}/tutor/save_tour`, {
    method: 'POST',
    headers: _headers(),
    body: JSON.stringify({
      project_id: projectId,
      tour_name: tourName,
      messages,
      depth_level: depthLevel,
    }),
  })
  if (!response.ok) throw new Error(`Save tour failed: ${response.status}`)
  return response.json()
}
