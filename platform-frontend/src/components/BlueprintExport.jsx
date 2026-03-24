import { useState } from 'react'
import { getBuildContext, generateBlueprint, downloadBlueprint } from '../services/blueprint.js'

export default function BlueprintExport({ projectId }) {
  const [blueprint, setBlueprint] = useState(null)
  const [loading, setLoading] = useState(false)
  const [downloaded, setDownloaded] = useState(false)

  async function handleGenerate() {
    setLoading(true)
    setBlueprint(null)
    setDownloaded(false)
    const context = await getBuildContext({ projectId })
    const bp = generateBlueprint({ projectId, context })
    setBlueprint(bp)
    setLoading(false)
  }

  function handleDownload() {
    if (!blueprint) return
    downloadBlueprint({ blueprint, projectId })
    setDownloaded(true)
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold text-midnight">Blueprint Export</h2>
        <p className="text-sm text-ink/60 mt-1">Package this build into a reusable Blueprint JSON file.</p>
      </div>

      <button onClick={handleGenerate} disabled={loading}
        className="w-full rounded-full bg-ember px-6 py-3 text-sm font-semibold text-white uppercase tracking-widest transition hover:bg-ember/80 disabled:opacity-50">
        {loading ? 'Generating...' : blueprint ? 'Regenerate' : 'Generate Blueprint'}
      </button>

      {blueprint && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-2xl border border-ink/10 bg-white/70 p-3 text-center shadow-sm">
              <p className="text-2xl font-bold text-ember">{blueprint.summary.total_agents}</p>
              <p className="text-xs text-ink/50 mt-1">Agents</p>
            </div>
            <div className="rounded-2xl border border-ink/10 bg-white/70 p-3 text-center shadow-sm">
              <p className="text-2xl font-bold text-ember">{blueprint.summary.total_tokens}</p>
              <p className="text-xs text-ink/50 mt-1">Tokens</p>
            </div>
            <div className="rounded-2xl border border-ink/10 bg-white/70 p-3 text-center shadow-sm">
              <p className="text-2xl font-bold text-ember">${blueprint.summary.total_cost}</p>
              <p className="text-xs text-ink/50 mt-1">Cost</p>
            </div>
          </div>

          <div className="rounded-2xl border border-ink/10 bg-white/70 p-4 shadow-sm">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink/50 mb-3">What was built</h3>
            <div className="space-y-2">
              {Object.entries(blueprint.task_ledger).map(([key, value]) => (
                <div key={key} className="flex justify-between text-sm">
                  <span className="text-ink/60 capitalize">{key.replace(/_/g, ' ')}</span>
                  <span className="font-medium text-midnight">{String(value)}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-ink/10 bg-white/70 p-4 shadow-sm">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink/50 mb-3">Agents</h3>
            <div className="space-y-2">
              {blueprint.aeg.nodes.map((node) => (
                <div key={node.id} className="flex items-center justify-between text-sm">
                  <span className="text-ink/70">{node.agent_type}</span>
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                    node.state === 'COMPLETED' ? 'bg-emerald-100 text-emerald-700' :
                    node.state === 'FAILED' ? 'bg-red-100 text-red-700' :
                    'bg-amber-100 text-amber-700'}`}>
                    {node.state}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-ink/10 bg-white/70 p-4 shadow-sm">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink/50 mb-3">JSON Preview</h3>
            <pre className="text-xs text-ink/70 overflow-auto max-h-40 whitespace-pre-wrap">
              {JSON.stringify(blueprint, null, 2).slice(0, 500)}...
            </pre>
          </div>

          <button onClick={handleDownload}
            className="w-full rounded-full bg-ember px-6 py-3 text-sm font-semibold text-white uppercase tracking-widest transition hover:bg-ember/80">
            {downloaded ? '✓ Downloaded!' : 'Download JSON'}
          </button>

          {downloaded && (
            <p className="text-center text-xs text-emerald-600">✓ Blueprint saved to your Downloads folder</p>
          )}
        </div>
      )}
    </div>
  )
}