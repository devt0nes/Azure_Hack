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

export const askQuestion = ({
  projectId,
  userMessage,
  conversationHistory = [],
  questionCount = 0,
}) =>
  apiFetch('/question', {
    method: 'POST',
    body: JSON.stringify({
      project_id: projectId,
      user_message: userMessage,
      conversation_history: conversationHistory,
      question_count: questionCount,
    }),
  })

export const checkQuestionReadiness = ({ projectId }) =>
  apiFetch('/question-readiness', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  })

export const executeFromSpecs = ({
  projectId,
  specPath = null,
  clarificationContext = null,
  serviceApiKeys = null,
}) =>
  apiFetch('/execute-from-specs', {
    method: 'POST',
    body: JSON.stringify({
      project_id: projectId,
      spec_path: specPath,
      clarification_context: clarificationContext,
      service_api_keys: serviceApiKeys,
    }),
  })

export const getProjectApiKeyStatus = ({ projectId }) =>
  apiFetch(`/api/projects/${projectId}/service-api-keys/status`)

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
export const createProject = ({ projectName, userIntent, description = '' }) =>
  apiFetch('/api/projects', {
    method: 'POST',
    body: JSON.stringify({
      project_name: projectName,
      user_intent: userIntent,
      description,
    }),
  })
export const getProject = ({ projectId }) => apiFetch(`/api/projects/${projectId}`)
export const getProjectPreviewStatus = ({ projectId }) => apiFetch(`/api/projects/${projectId}/preview-status`)
export const getProjectLogs = ({ projectId }) => apiFetch(`/api/projects/${projectId}/logs`)
export const getProjectAgentEvents = ({ projectId }) => apiFetch(`/api/projects/${projectId}/agent-events`)
export const listProjectArtifacts = ({ projectId }) => apiFetch(`/api/projects/${projectId}/artifacts`)
export const getWorkspaceFiles = ({ projectId }) => apiFetch(`/api/projects/${projectId}/workspace-files`)
export const getProjectSpecs = ({ projectId }) => apiFetch(`/api/projects/${projectId}/specs`)
export const getProjectLedger = ({ projectId }) => apiFetch(`/api/projects/${projectId}/ledger`)

export const saveCanvas = ({ projectId, canvasData }) =>
  apiFetch(`/api/projects/${projectId}/canvas`, {
    method: 'PUT',
    body: JSON.stringify({ canvas_data: canvasData }),
  })

export const loadCanvas = ({ projectId }) =>
  apiFetch(`/api/projects/${projectId}/canvas`)

export const ingestProjectContext = ({
  projectId,
  referenceFiles = [],
  includeCanvas = false,
}) =>
  apiFetch(`/api/projects/${projectId}/ingestion/context`, {
    method: 'POST',
    body: JSON.stringify({
      reference_files: referenceFiles.map((file) => ({
        filename: file.filename,
        url: file.url,
      })),
      include_canvas: includeCanvas,
    }),
  })

export async function uploadCanvasFile({ projectId, file }) {
  requireApiBaseUrl()
  const token = await getToken()

  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/canvas/upload`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: formData,
  })

  if (response.status === 401) {
    window.location.href = '/'
    throw new Error('Unauthorized')
  }

  if (!response.ok) {
    throw new Error(`Failed to upload canvas file for project: ${projectId}`)
  }

  return response.json()
}

export async function downloadProjectArtifact({ projectId, artifactName }) {
  requireApiBaseUrl()
  const token = await getToken()

  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/artifacts/${encodeURIComponent(artifactName)}`,
    {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  )

  if (response.status === 401) {
    window.location.href = '/'
    throw new Error('Unauthorized')
  }

  if (!response.ok) {
    throw new Error(`Failed to download artifact: ${artifactName}`)
  }

  const blob = await response.blob()
  return { blob, filename: artifactName }
}