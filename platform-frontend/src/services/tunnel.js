/**
 * Day 4: Dev Tunnel service
 * Manages preview URL for generated code
 */

/**
 * Get the preview URL for generated code
 */
export async function getTunnelUrl(projectId) {
  if (!projectId) {
    return {
      url: null,
      status: 'no-project',
      message: 'No project selected'
    }
  }
  
  const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
  const previewUrl = `${apiBase}/api/preview/${projectId}/`
  
  return {
    url: previewUrl,
    status: 'ready',
    projectId: projectId,
  }
}

/**
 * Check if running in Docker container
 */
export function isDockerEnvironment() {
  const apiUrl = import.meta.env.VITE_API_BASE_URL || ''
  return apiUrl.includes('backend:8000')
}

/**
 * Get preview URL based on environment
 */
export function getPreviewUrl() {
  if (isDockerEnvironment()) {
    return 'http://backend:8000'
  }
  return import.meta.env.VITE_PREVIEW_URL || 'http://localhost:8000'
}

