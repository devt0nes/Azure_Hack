import { useEffect, useState } from 'react'
import { getTunnelUrl } from '../services/tunnel.js'
import { getProject } from '../services/api.js'

export default function Preview({ currentProjectId, projectData }) {
  const [tunnelInfo, setTunnelInfo] = useState(null)
  const [currentProject, setCurrentProject] = useState(projectData)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [iframeError, setIframeError] = useState(false)

  useEffect(() => {
    loadTunnelInfo()
  }, [currentProjectId, refreshKey])

  useEffect(() => {
    if (projectData) {
      setCurrentProject(projectData)
    }
  }, [projectData])

  async function loadTunnelInfo() {
    setLoading(true)
    setError(null)
    setIframeError(false)
    setTunnelInfo(null)  // Clear tunnel info to prevent old iframe from loading
    
    try {
      if (!currentProjectId) {
        setLoading(false)
        return
      }
      
      // Fetch current project data
      const projectStatus = await getProject({ projectId: currentProjectId })
      setCurrentProject(projectStatus)
      
      // Only construct preview URL if project is completed
      // This prevents 404 errors from trying to load non-existent files
      if (projectStatus?.status === 'completed') {
        const info = await getTunnelUrl(currentProjectId)
        setTunnelInfo(info)
      }
    } catch (err) {
      console.error('Preview load error:', err)
      // Don't set error state, just clear tunnel info
    } finally {
      setLoading(false)
    }
  }

  const handleRefresh = () => {
    setRefreshKey((prev) => prev + 1)
  }

  const handleOpenExternal = () => {
    if (tunnelInfo?.url) {
      window.open(tunnelInfo.url, '_blank')
    }
  }

  const handleIframeError = () => {
    setIframeError(true)
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-ink/70">Generated Code Preview</p>
          <p className="mt-1 text-xs text-ink/50">
            {loading && 'Loading preview...'}
            {!loading && currentProject?.status === 'completed' && 'Project complete - preview ready'}
            {!loading && currentProject?.status === 'generating_code' && 'Generating code...'}
            {!loading && currentProject?.status === 'created' && 'Waiting to start generation'}
            {!loading && currentProject?.status === 'queued' && 'Queued for generation'}
            {!loading && !currentProjectId && 'No project selected'}
            {error && 'Preview unavailable'}
          </p>
        </div>

        {/* Controls */}
        <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
          <button
            onClick={handleRefresh}
            className="rounded-md bg-ink/5 px-3 py-1.5 text-xs font-medium text-ink/70 transition hover:bg-ink/10"
            disabled={loading}
          >
            Refresh
          </button>
          <button
            onClick={handleOpenExternal}
            className="rounded-md bg-ember px-3 py-1.5 text-xs font-medium text-white transition hover:bg-ember/90"
            disabled={!tunnelInfo?.url || loading || !currentProjectId}
          >
            Open External
          </button>
        </div>
      </div>

      {/* Project Info Display */}
      {currentProject && currentProjectId && (
        <div className="mb-3 rounded-lg border border-ink/10 bg-sand/30 px-3 py-2">
          <p className="text-xs font-mono text-ink/60">
            <span className="font-semibold">Project:</span> {currentProject.project_name || 'Untitled'} ({currentProjectId?.slice(0, 8)})
          </p>
          <p className="mt-1 text-xs text-ink/50">
            Status: <span className="font-semibold">{currentProject.status || 'unknown'}</span> • Progress: {currentProject.progress || 0}%
          </p>
        </div>
      )}

      {/* Tunnel URL Display */}
      {tunnelInfo?.url && (
        <div className="mb-3 rounded-lg border border-ink/10 bg-sand/30 px-3 py-2">
          <p className="text-xs font-mono text-ink/60">
            <span className="font-semibold">URL:</span> {tunnelInfo.url}
          </p>
        </div>
      )}

      {/* Preview iframe */}
      <div className="h-[380px] min-h-[320px] flex-1 transition-all duration-200">
        {loading && (
          <div className="flex h-full items-center justify-center rounded-lg border border-ink/10 bg-white/60">
            <p className="text-sm text-ink/50">Loading preview...</p>
          </div>
        )}

        {error && (
          <div className="flex h-full items-center justify-center rounded-lg border border-red-200 bg-red-50">
            <div className="text-center">
              <p className="text-sm font-medium text-red-700">Preview unavailable</p>
              <p className="mt-1 text-xs text-red-600">{error}</p>
            </div>
          </div>
        )}

        {!loading && !error && tunnelInfo?.url && !iframeError && (
          <iframe
            key={refreshKey}
            src={tunnelInfo.url}
            onError={handleIframeError}
            className="h-full w-full rounded-lg border border-ink/10 bg-white"
            title="Generated Code Preview"
            sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-pointer-lock"
          />
        )}

        {!loading && !error && iframeError && (
          <div className="flex h-full items-center justify-center rounded-lg border border-yellow-200 bg-yellow-50">
            <div className="text-center">
              <p className="text-sm font-medium text-yellow-700">Preview file not found</p>
              <p className="mt-1 text-xs text-yellow-600">The generated code may not have been written to disk yet</p>
            </div>
          </div>
        )}

        {!loading && !error && !tunnelInfo?.url && currentProjectId && (
          <div className="flex h-full items-center justify-center rounded-lg border border-ink/10 bg-haze/30">
            <div className="text-center">
              <p className="text-sm text-ink/60">
                {currentProject?.status === 'generating_code' 
                  ? 'Generating code...' 
                  : 'Preview will be available once code generation completes'}
              </p>
              <p className="mt-1 text-xs text-ink/50">Current status: {currentProject?.status || 'unknown'}</p>
            </div>
          </div>
        )}

        {!loading && !error && !currentProjectId && (
          <div className="flex h-full items-center justify-center rounded-lg border border-ink/10 bg-haze/30">
            <p className="text-sm text-ink/50">Select or create a project to see the preview</p>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="mt-3 rounded-lg border border-ink/10 bg-haze/50 px-3 py-2">
        <p className="text-xs text-ink/60">
          <span className="font-semibold">Info:</span> The preview shows the generated frontend code in real-time
        </p>
      </div>
    </div>
  )
}
