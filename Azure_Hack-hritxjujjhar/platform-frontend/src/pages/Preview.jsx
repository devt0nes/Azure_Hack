import { useEffect, useState } from 'react'
import { deployProject, getDeploymentStatus, getProject, getProjectPreviewStatus } from '../services/api.js'

export default function Preview({ currentProjectId, projectData }) {
  const [tunnelInfo, setTunnelInfo] = useState(null)
  const [currentProject, setCurrentProject] = useState(projectData)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [iframeError, setIframeError] = useState(false)
  const [deploying, setDeploying] = useState(false)
  const [deploymentInfo, setDeploymentInfo] = useState(null)
  const [deploymentError, setDeploymentError] = useState(null)

  useEffect(() => {
    loadTunnelInfo()
  }, [currentProjectId, refreshKey])

  useEffect(() => {
    if (!currentProjectId) {
      setDeploymentInfo(null)
      setDeploymentError(null)
      return
    }

    let active = true

    const readDeploymentStatus = async () => {
      try {
        const status = await getDeploymentStatus({ projectId: currentProjectId })
        if (active) {
          setDeploymentInfo(status)
          setDeploymentError(null)
        }
      } catch (err) {
        if (active) setDeploymentError('Deployment status unavailable')
      }
    }

    readDeploymentStatus()
    const timer = window.setInterval(readDeploymentStatus, 5000)

    return () => {
      active = false
      window.clearInterval(timer)
    }
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
      
      // Route preview as soon as frontend artifacts are available.
      const previewStatus = await getProjectPreviewStatus({ projectId: currentProjectId })
      if (previewStatus?.preview_ready && previewStatus?.preview_url) {
        const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
        setTunnelInfo({
          url: `${apiBase}${previewStatus.preview_url}`,
          status: 'ready',
          projectId: currentProjectId
        })
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

  const handleDeploy = async () => {
    if (!currentProjectId || deploying) return
    setDeploying(true)
    setDeploymentError(null)
    try {
      await deployProject({ projectId: currentProjectId })
      setRefreshKey((prev) => prev + 1)
    } catch (err) {
      setDeploymentError('Failed to start deployment')
    } finally {
      setDeploying(false)
    }
  }

  const canDeploy = currentProject?.status === 'completed' && !!currentProjectId

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground/80">Generated Code Preview</p>
          <p className="mt-1 text-xs text-foreground/50">
            {loading
              ? 'Loading preview...'
              : error
                ? 'Preview unavailable'
                : tunnelInfo?.url
                  ? 'Frontend preview ready'
                  : !currentProjectId
                    ? 'No project selected'
                    : currentProject?.status === 'queued'
                      ? 'Queued for generation'
                      : currentProject?.status === 'created'
                        ? 'Waiting to start generation'
                        : currentProject?.status === 'generating_code'
                          ? 'Generating code...'
                          : currentProject?.status === 'completed'
                            ? 'Project complete - preview ready'
                            : `Current status: ${currentProject?.status || 'unknown'}`}
          </p>
        </div>

        {/* Controls */}
        <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
          <button
            onClick={handleDeploy}
            className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-700 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canDeploy || deploying || currentProject?.status === 'generating_deployment'}
          >
            {deploying || currentProject?.status === 'generating_deployment' ? 'Deploying...' : 'Deploy to Azure'}
          </button>
          <button
            onClick={handleRefresh}
            className="rounded-md border border-border bg-secondary px-3 py-1.5 text-xs font-medium text-foreground/70 transition hover:bg-accent"
            disabled={loading}
          >
            Refresh
          </button>
          <button
            onClick={handleOpenExternal}
            className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition hover:bg-primary/20"
            disabled={!tunnelInfo?.url || loading || !currentProjectId}
          >
            Open External
          </button>
        </div>
      </div>

      {/* Project Info Display */}
      {currentProject && currentProjectId && (
        <div className="mb-3 rounded-lg border border-border bg-secondary/40 px-3 py-2">
          <p className="text-xs font-mono text-foreground/60">
            <span className="font-semibold">Project:</span> {currentProject.project_name || 'Untitled'} ({currentProjectId?.slice(0, 8)})
          </p>
          <p className="mt-1 text-xs text-foreground/50">
            Status: <span className="font-semibold">{currentProject.status || 'unknown'}</span> • Progress: {currentProject.progress || 0}%
          </p>
        </div>
      )}

      {/* Tunnel URL Display */}
      {tunnelInfo?.url && (
        <div className="mb-3 rounded-lg border border-border bg-secondary/40 px-3 py-2">
          <p className="text-xs font-mono text-foreground/60">
            <span className="font-semibold">URL:</span> {tunnelInfo.url}
          </p>
        </div>
      )}

      {(deploymentInfo || deploymentError) && (
        <div className="mb-3 rounded-lg border border-border bg-secondary/40 px-3 py-2">
          <p className="text-xs text-foreground/60">
            <span className="font-semibold">Deployment:</span>{' '}
            {deploymentError
              ? deploymentError
              : deploymentInfo?.deployment_result?.message || deploymentInfo?.deployment_status || 'idle'}
          </p>
          {deploymentInfo?.deployment_result?.details?.frontend_url && (
            <p className="mt-1 text-xs text-foreground/50">
              Frontend URL: {deploymentInfo.deployment_result.details.frontend_url}
            </p>
          )}
        </div>
      )}

      {/* Preview iframe */}
      <div className="h-[380px] min-h-[320px] flex-1 transition-all duration-200">
        {loading && (
          <div className="flex h-full items-center justify-center rounded-lg border border-border bg-secondary/40">
            <p className="text-sm text-foreground/50">Loading preview...</p>
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
            className="h-full w-full rounded-lg border border-border bg-card"
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
          <div className="flex h-full items-center justify-center rounded-lg border border-border bg-secondary/40">
            <div className="text-center">
              <p className="text-sm text-foreground/60">
                {currentProject?.status === 'generating_code' 
                  ? 'Generating code...' 
                  : 'Preview will be available once code generation completes'}
              </p>
              <p className="mt-1 text-xs text-foreground/50">Current status: {currentProject?.status || 'unknown'}</p>
            </div>
          </div>
        )}

        {!loading && !error && !currentProjectId && (
          <div className="flex h-full items-center justify-center rounded-lg border border-border bg-secondary/40">
            <p className="text-sm text-foreground/50">Select or create a project to see the preview</p>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="mt-3 rounded-lg border border-border bg-secondary/40 px-3 py-2">
        <p className="text-xs text-foreground/60">
          <span className="font-semibold">Info:</span> The preview shows the generated frontend code in real-time
        </p>
      </div>
    </div>
  )
}
