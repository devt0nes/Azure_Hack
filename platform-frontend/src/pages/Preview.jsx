import { useEffect, useState } from 'react'
import { getTunnelUrl } from '../services/tunnel.js'

export default function Preview() {
  const [tunnelInfo, setTunnelInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    loadTunnelInfo()
  }, [refreshKey])

  async function loadTunnelInfo() {
    setLoading(true)
    setError(null)
    try {
      const info = await getTunnelUrl()
      setTunnelInfo(info)
    } catch (err) {
      setError(err.message)
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

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-ink/70">Local Preview</p>
          <p className="mt-1 text-xs text-ink/50">
            {loading && 'Loading tunnel info...'}
            {!loading && tunnelInfo?.status === 'local' && 'Running on localhost'}
            {!loading && tunnelInfo?.status === 'active' && `Tunnel active on port ${tunnelInfo.port}`}
            {error && 'Failed to load tunnel info'}
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
            disabled={!tunnelInfo?.url || loading}
          >
            Open External
          </button>
        </div>
      </div>

      {/* Tunnel URL Display */}
      {tunnelInfo?.url && (
        <div className="mb-3 rounded-lg border border-ink/10 bg-sand/30 px-3 py-2">
          <p className="text-xs font-mono text-ink/60">
            <span className="font-semibold">URL:</span> {tunnelInfo.url}
          </p>
          {tunnelInfo.status === 'local' && (
            <p className="mt-1 text-xs text-ink/50">
              Run <code className="rounded bg-ink/10 px-1 py-0.5">start-devtunnel.ps1</code> to
              expose via public URL
            </p>
          )}
        </div>
      )}

      {/* Preview iframe */}
      <div className="h-[380px] min-h-[320px] transition-all duration-200">
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

        {!loading && !error && tunnelInfo?.url && (
          <iframe
            key={refreshKey}
            src={tunnelInfo.url}
            className="h-full w-full rounded-lg border border-ink/10 bg-white"
            title="Local Preview"
            sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
          />
        )}
      </div>

      {/* Docker hint */}
      <div className="mt-3 rounded-lg border border-ink/10 bg-haze/50 px-3 py-2">
        <p className="text-xs text-ink/60">
          <span className="font-semibold">Docker Compose:</span> Run{' '}
          <code className="rounded bg-ink/10 px-1 py-0.5">
            docker-compose -f infrastructure/docker-compose.template.yml up
          </code>{' '}
          for hot-reload
        </p>
      </div>
    </div>
  )
}

