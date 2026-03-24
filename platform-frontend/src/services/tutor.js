const TUTOR_API_URL = import.meta.env.VITE_TUTOR_API_URL || import.meta.env.VITE_API_BASE_URL || ''
const TUTOR_API_KEY = import.meta.env.VITE_TUTOR_API_KEY || ''

export async function askTutor({ projectId, question, context = {} }) {
  if (!TUTOR_API_URL) {
    throw new Error('Tutor API URL is not configured')
  }

  const response = await fetch(`${TUTOR_API_URL}/tutor/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(TUTOR_API_KEY && { Authorization: `Bearer ${TUTOR_API_KEY}` }),
    },
    body: JSON.stringify({
      project_id: projectId,
      question,
      context,
    }),
  })

  if (!response.ok) {
    throw new Error('Tutor request failed')
  }

  return response.json()
}
