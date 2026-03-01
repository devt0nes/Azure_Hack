/**
 * Day 4: Dev Tunnel service
 * Manages tunnel URL retrieval and status checking
 */

const TUNNEL_CHECK_ENDPOINT = '/api/tunnel-status'

/**
 * Get the active Dev Tunnel URL
 * In production, this would query the backend for tunnel status
 * For local dev, reads from environment or falls back to localhost
 */
export async function getTunnelUrl() {
  try {
    // Check if backend has tunnel info
    const baseUrl = import.meta.env.VITE_API_BASE_URL
    if (baseUrl) {
      const response = await fetch(`${baseUrl}${TUNNEL_CHECK_ENDPOINT}`)
      if (response.ok) {
        const data = await response.json()
        return {
          url: data.tunnel_url,
          status: data.status,
          port: data.port,
        }
      }
    }
  } catch (error) {
    console.warn('Tunnel status check failed, using fallback:', error.message)
  }

  // Fallback to environment variable or localhost
  const fallbackUrl = import.meta.env.VITE_PREVIEW_URL || 'http://localhost:5173'
  return {
    url: fallbackUrl,
    status: 'local',
    port: 5173,
  }
}

/**
 * Check if running in Docker container
 */
export function isDockerEnvironment() {
  // Check if API_BASE_URL points to backend container
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
