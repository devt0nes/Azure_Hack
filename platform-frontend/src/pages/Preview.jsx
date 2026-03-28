import { useEffect, useRef, useState } from 'react'
import {
  downloadProjectArtifact,
  getDeploymentStatus,
  getProject,
  getProjectPreviewStatus,
  listProjectArtifacts,
} from '../services/api.js'

export default function Preview({ currentProjectId, projectData, compactInfo = false }) {
  const [tunnelInfo, setTunnelInfo] = useState(null)
  const [currentProject, setCurrentProject] = useState(projectData)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [iframeError, setIframeError] = useState(false)
  const [deploymentInfo, setDeploymentInfo] = useState(null)
  const [deploymentError, setDeploymentError] = useState(null)
  const [deploymentNotice, setDeploymentNotice] = useState('')
  const [deployMenuOpen, setDeployMenuOpen] = useState(false)
  const deployMenuRef = useRef(null)

  useEffect(() => {
    loadTunnelInfo()
  }, [currentProjectId, refreshKey])

  useEffect(() => {
    if (!currentProjectId) return undefined

    const timer = window.setInterval(() => {
      loadTunnelInfo({ silent: true })
    }, 5000)

    return () => {
      window.clearInterval(timer)
    }
  }, [currentProjectId])

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

  useEffect(() => {
    const handleDocumentClick = (event) => {
      if (!deployMenuRef.current) return
      if (!deployMenuRef.current.contains(event.target)) {
        setDeployMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', handleDocumentClick)
    return () => document.removeEventListener('mousedown', handleDocumentClick)
  }, [])

  async function loadTunnelInfo(options = {}) {
    const { silent = false } = options

    if (!silent) {
      setLoading(true)
      setError(null)
      setIframeError(false)
      setTunnelInfo(null)
    }

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
      if (!silent) {
        setLoading(false)
      }
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

  const handleDeployToAzure = () => {
    setDeployMenuOpen(false)
    if (!currentProjectId) {
      setDeploymentError('Select a project before deploying to Azure.')
      return
    }
    setDeploymentError(null)
    setDeploymentNotice('Opening Microsoft login...')
    window.open('https://login.microsoftonline.com/', '_blank', 'noopener,noreferrer')
  }

  const handleSaveFilesLocally = async () => {
    setDeployMenuOpen(false)
    if (!currentProjectId) {
      setDeploymentError('Select a project before saving deployment files locally.')
      return
    }

    setDeploymentError(null)
    setDeploymentNotice('Preparing local files...')

    try {
      const artifactPayload = await listProjectArtifacts({ projectId: currentProjectId })
      const artifacts = Array.isArray(artifactPayload?.artifacts) ? artifactPayload.artifacts : []

      if (artifacts.length === 0) {
        setDeploymentNotice('No generated artifacts available to download yet.')
        return
      }

      const topLevelArtifacts = artifacts.filter((artifact) => !String(artifact?.path || '').includes('/'))
      let downloaded = 0
      let failed = 0

      for (const artifact of topLevelArtifacts) {
        const fileName = String(artifact?.name || '').trim()
        if (!fileName) continue

        try {
          const { blob, filename } = await downloadProjectArtifact({
            projectId: currentProjectId,
            artifactName: fileName,
          })

          const url = URL.createObjectURL(blob)
          const anchor = document.createElement('a')
          anchor.href = url
          anchor.download = filename
          document.body.appendChild(anchor)
          anchor.click()
          anchor.remove()
          URL.revokeObjectURL(url)
          downloaded += 1

          await new Promise((resolve) => setTimeout(resolve, 80))
        } catch (downloadErr) {
          failed += 1
        }
      }

      const skippedNested = artifacts.length - topLevelArtifacts.length
      setDeploymentNotice(
        `Downloaded ${downloaded} file(s)` +
        (skippedNested > 0 ? `, skipped ${skippedNested} nested file(s)` : '') +
        '.'
      )

      if (failed > 0) {
        setDeploymentError(`Failed to download ${failed} file(s).`)
      }
    } catch (err) {
      setDeploymentError('Unable to fetch project artifacts for local save.')
      setDeploymentNotice('')
    }
  }

  const hasProjectSelected = !!currentProjectId
  const infoMessage = 'The preview shows the generated frontend code in real-time'

  return (
    <div className="h-full min-h-0 min-w-0 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-foreground/80">Generated Code Preview</p>
            <div className="group relative">
              <button
                type="button"
                aria-label="Preview info"
                className="flex h-4 w-4 items-center justify-center rounded-full border border-border text-[10px] font-semibold leading-none text-foreground/70 transition hover:bg-accent"
              >
                i
              </button>
              <div className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 hidden w-64 -translate-x-1/2 rounded-md border border-border bg-card px-2.5 py-2 text-[11px] text-foreground/70 shadow-lg group-hover:block">
                {infoMessage}
              </div>
            </div>
          </div>
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
          <div className="relative" ref={deployMenuRef}>
            <button
              onClick={() => setDeployMenuOpen((prev) => !prev)}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-700 transition hover:bg-emerald-500/20"
            >
              Deploy
              <svg
                className={`h-3.5 w-3.5 transition-transform ${deployMenuOpen ? 'rotate-180' : ''}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>

            {deployMenuOpen && (
              <div className="absolute right-0 z-20 mt-2 w-52 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
                <button
                  onClick={handleDeployToAzure}
                  disabled={!hasProjectSelected}
                  className="block w-full border-b border-border/60 px-3 py-2 text-left text-xs font-medium text-foreground transition hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Deploy to Azure
                </button>
                <button
                  onClick={handleSaveFilesLocally}
                  disabled={!hasProjectSelected}
                  className="block w-full px-3 py-2 text-left text-xs font-medium text-foreground transition hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Save files locally
                </button>
                {!hasProjectSelected && (
                  <p className="border-t border-border/60 px-3 py-2 text-[11px] text-foreground/50">
                    Select a project first.
                  </p>
                )}
              </div>
            )}
          </div>
          <button
            onClick={handleRefresh}
            title="Refresh preview"
            aria-label="Refresh preview"
            className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border bg-secondary text-foreground/70 transition hover:bg-accent"
            disabled={loading}
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a9 9 0 1 1-2.64-6.36" />
              <path d="M21 3v6h-6" />
            </svg>
          </button>
          <button
            onClick={handleOpenExternal}
            title="Open preview in a new tab"
            aria-label="Open preview in a new tab"
            className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-primary/40 bg-primary/10 text-primary transition hover:bg-primary/20"
            disabled={!tunnelInfo?.url || loading || !currentProjectId}
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 3h7v7" />
              <path d="M10 14L21 3" />
              <path d="M21 14v7H3V3h7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Tunnel URL Display */}
      {tunnelInfo?.url && (
        <div className="mb-3 rounded-lg border border-border bg-secondary/40 px-3 py-2">
          <p className="break-all text-xs font-mono text-foreground/60">
            <span className="font-semibold">URL:</span> {tunnelInfo.url}
          </p>
        </div>
      )}

      {deploymentNotice ? (
        <div className="mb-3 rounded-lg border border-primary/30 bg-primary/10 px-3 py-2">
          <p className="text-xs text-primary">{deploymentNotice}</p>
        </div>
      ) : null}

      {/* Preview iframe */}
      <div className="min-h-0 flex-1 overflow-hidden transition-all duration-200">
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

      {/* Combined project + deployment summary */}
      {currentProject && currentProjectId && (
        <div className="mt-3 rounded-lg border border-border bg-secondary/40 px-3 py-2">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-mono text-foreground/60">
                <span className="font-semibold">Project:</span> {currentProject.project_name || 'Untitled'} ({currentProjectId?.slice(0, 8)})
              </p>
              <p className="mt-1 text-xs text-foreground/50">
                Status: <span className="font-semibold">{currentProject.status || 'unknown'}</span> • Progress: {currentProject.progress || 0}%
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-foreground/60">
                <span className="font-semibold">Deployment:</span>{' '}
                {deploymentError
                  ? deploymentError
                  : deploymentInfo?.deployment_result?.message || deploymentInfo?.deployment_status || 'created'}
              </p>
              {deploymentInfo?.deployment_result?.details?.frontend_url && (
                <p className="mt-1 max-w-[220px] break-all text-xs text-foreground/50">
                  {deploymentInfo.deployment_result.details.frontend_url}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
