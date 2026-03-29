import { useEffect, useState, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import ReactFlow, {
  Background,
  Controls,
  useNodesState,
  useEdgesState,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { getAEG, getProjectLedger } from '../services/api.js'

const STATE_COLORS = {
  PENDING: '#1c1c24',
  RUNNING: '#f26a2e',
  COMPLETED: '#10b981',
  FAILED: '#ef4444',
}

const FLASH_ANIMATION = `
  @keyframes nodeFlash {
    0%, 100% { filter: brightness(1) drop-shadow(0 0 8px rgba(242, 106, 46, 0.4)); }
    50% { filter: brightness(1.2) drop-shadow(0 0 16px rgba(242, 106, 46, 0.8)); }
  }
  .node-running {
    animation: nodeFlash 1.2s ease-in-out infinite !important;
  }
`

const nodeTypes = {}

function titleCaseText(value) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function toAgentRole(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'object') {
    return String(value.role || value.agent_name || value.id || value.name || '').trim()
  }
  return ''
}

function getLayerAgents(layer) {
  if (!layer) return []
  if (Array.isArray(layer)) {
    return layer.map(toAgentRole).filter(Boolean)
  }
  if (typeof layer === 'object') {
    const candidates = [
      layer.agents,
      layer.required_agents,
      layer.parallel_agents,
      layer.members,
      layer.roles,
    ]
    for (const candidate of candidates) {
      if (Array.isArray(candidate)) {
        return candidate.map(toAgentRole).filter(Boolean)
      }
    }
  }
  return []
}

function extractLayersFromPayload(payload = {}, fallbackSpecs = {}) {
  const taskLedger = payload?.task_ledger || {}
  const specs = payload?.agent_specifications || fallbackSpecs || {}

  const fromTaskLedger = Array.isArray(taskLedger?.layers) ? taskLedger.layers : null
  const fromSpecsLayers = Array.isArray(specs?.layers) ? specs.layers : null
  const fromParallel = Array.isArray(specs?.parallel_execution_groups)
    ? specs.parallel_execution_groups
    : null

  let rawLayers = fromTaskLedger || fromSpecsLayers || fromParallel || []
  if (!Array.isArray(rawLayers) || rawLayers.length === 0) {
    const required = Array.isArray(specs?.required_agents) ? specs.required_agents : []
    const requiredRoles = required.map(toAgentRole).filter(Boolean)
    rawLayers = requiredRoles.length > 0 ? [requiredRoles] : []
  }

  return rawLayers.map((layer, index) => {
    const agents = getLayerAgents(layer)
    const layerNumber = index + 1
    const title =
      typeof layer === 'object' && !Array.isArray(layer)
        ? String(layer.title || layer.name || `Layer ${layerNumber}`)
        : `Layer ${layerNumber}`

    return {
      id: `layer-${layerNumber}`,
      index: layerNumber,
      title,
      agents,
      raw: layer,
    }
  })
}

function deriveLayerState(layerAgents, agentStatusMap = {}) {
  const statuses = layerAgents
    .map((agent) => agentStatusMap[agent]?.state)
    .filter(Boolean)

  if (statuses.includes('FAILED')) return 'FAILED'
  if (statuses.includes('RUNNING')) return 'RUNNING'
  if (statuses.length > 0 && statuses.every((status) => status === 'COMPLETED')) return 'COMPLETED'
  return 'PENDING'
}

function deriveLayerProgress(layerAgents, agentStatusMap = {}) {
  const progresses = layerAgents
    .map((agent) => Number(agentStatusMap[agent]?.progress ?? 0))
    .filter((value) => Number.isFinite(value))

  if (progresses.length === 0) return 0
  const average = progresses.reduce((sum, value) => sum + value, 0) / progresses.length
  return Math.max(0, Math.min(100, Math.round(average)))
}

function extractBlackboardNotes(layer, payload = {}) {
  const notes = []
  const taskLedger = payload?.task_ledger || {}

  const pushNote = (value) => {
    if (!value) return
    if (Array.isArray(value)) {
      value.forEach(pushNote)
      return
    }
    if (typeof value === 'object') {
      Object.entries(value).forEach(([k, v]) => {
        if (v == null) return
        if (typeof v === 'string' || typeof v === 'number') {
          notes.push(`${titleCaseText(k)}: ${String(v)}`)
        }
      })
      return
    }
    notes.push(String(value))
  }

  if (typeof layer?.raw === 'object' && layer.raw && !Array.isArray(layer.raw)) {
    pushNote(layer.raw.blackboard)
    pushNote(layer.raw.coordination_blackboard)
    pushNote(layer.raw.coordination_expectations)
    pushNote(layer.raw.notes)
    pushNote(layer.raw.summary)
    pushNote(layer.raw.deliverables)
    pushNote(layer.raw.how)
  }

  const boardStore =
    taskLedger?.layer_blackboards ||
    taskLedger?.layer_blackboard ||
    taskLedger?.blackboard ||
    {}

  if (boardStore && typeof boardStore === 'object') {
    const keys = [layer.id, String(layer.index), `layer_${layer.index}`, layer.title]
    keys.forEach((key) => {
      if (key in boardStore) {
        pushNote(boardStore[key])
      }
    })
  }

  return Array.from(new Set(notes.map((note) => String(note).trim()).filter(Boolean))).slice(0, 8)
}

function toLayerFlowGraph({ aegPayload, ledgerPayload, agentStatusMap = {} }) {
  const ledgerData = ledgerPayload?.ledger_data || {}
  const fallbackSpecs = aegPayload?.agent_specifications || {}

  const layers = extractLayersFromPayload(ledgerData, fallbackSpecs)
  if (layers.length === 0) {
    throw new Error('No task ledger layers found for AEG')
  }

  const flowNodes = layers.map((layer, idx) => {
    const progress = deriveLayerProgress(layer.agents, agentStatusMap)
    const state = deriveLayerState(layer.agents, agentStatusMap)
    const isRunning = state === 'RUNNING'

    return {
      id: layer.id,
      type: 'default',
      position: { x: idx * 260 + 30, y: 80 },
      data: {
        label: (
          <div className="text-left leading-tight">
            <div className="font-semibold text-[11px]">{layer.title}</div>
            <div className="mono text-[10px] mt-1">{progress}% complete</div>
            <div className={`mono text-[8px] uppercase tracking-wider mt-1 ${isRunning ? 'text-amber-200 font-semibold' : 'text-white/85'}`}>
              {state}
            </div>
            <div className="text-[8px] mt-1 text-white/75">
              Parallel agents: {layer.agents.length}
            </div>
          </div>
        ),
      },
      style: {
        background: STATE_COLORS[state] || STATE_COLORS.PENDING,
        color: '#ffffff',
        border: `3px solid ${STATE_COLORS[state] || '#f26a2e'}`,
        borderRadius: '12px',
        padding: '12px 14px',
        fontSize: '11px',
        width: 205,
        boxShadow: isRunning
          ? '0 0 16px rgba(242, 106, 46, 0.8), inset 0 0 8px rgba(242, 106, 46, 0.3)'
          : '0 2px 8px rgba(0, 0, 0, 0.5)',
        outline: `1px solid ${STATE_COLORS[state]}40`,
      },
      className: isRunning ? 'node-running' : '',
    }
  })

  const flowEdges = layers.slice(0, -1).map((layer, idx) => ({
    id: `${layer.id}-${layers[idx + 1].id}`,
    source: layer.id,
    target: layers[idx + 1].id,
    animated: true,
    style: { stroke: '#f26a2e', strokeWidth: 2 },
  }))

  const blackboardByLayer = layers.reduce((acc, layer) => {
    acc[layer.id] = extractBlackboardNotes(layer, ledgerData)
    return acc
  }, {})

  return {
    layers,
    flowNodes,
    flowEdges,
    blackboardByLayer,
  }
}

export default function AEGView({ projectId, onNodeSelect, agents = [] }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [graphMeta, setGraphMeta] = useState({ projectName: '', source: '' })
  const [layers, setLayers] = useState([])
  const [blackboardByLayer, setBlackboardByLayer] = useState({})
  const [selectedLayerId, setSelectedLayerId] = useState(null)
  const [isFocused, setIsFocused] = useState(false)

  const agentStatusMap = useMemo(() => {
    const map = {}
    agents.forEach((agent) => {
      map[agent.id] = {
        state: agent.state,
        progress: agent.progress,
      }
    })
    return map
  }, [agents])

  const fetchAEG = useCallback(async (options = {}) => {
    const { silent = false } = options

    if (!projectId) {
      setNodes([])
      setEdges([])
      setGraphMeta({ projectName: '', source: '' })
      setError('No project selected yet.')
      setIsLoading(false)
      return
    }

    try {
      if (!silent) {
        setIsLoading(true)
      }
      setError('')
      const [aegResult, ledgerResult] = await Promise.allSettled([
        getAEG({ projectId }),
        getProjectLedger({ projectId }),
      ])

      const aegData = aegResult.status === 'fulfilled' ? aegResult.value : {}
      const ledgerData = ledgerResult.status === 'fulfilled' ? ledgerResult.value : {}

      const { flowNodes, flowEdges, layers: layerRows, blackboardByLayer: board } = toLayerFlowGraph({
        aegPayload: aegData,
        ledgerPayload: ledgerData,
        agentStatusMap,
      })

      setNodes(flowNodes)
      setEdges(flowEdges)
      setLayers(layerRows)
      setBlackboardByLayer(board)
      setSelectedLayerId((prev) => prev || layerRows[0]?.id || null)
      setGraphMeta({
        projectName: aegData?.project_name || aegData?.projectId || projectId,
        source: 'api',
      })
    } catch (fetchError) {
      console.error(fetchError)
      if (!silent) {
        setError('Unable to load AEG. Ensure backend is running and a project exists.')
        setNodes([])
        setEdges([])
        setLayers([])
        setBlackboardByLayer({})
        setSelectedLayerId(null)
        setGraphMeta({ projectName: '', source: '' })
      }
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
    }
  }, [projectId, setNodes, setEdges, agentStatusMap])

  useEffect(() => {
    if (!selectedLayerId && layers.length > 0) {
      setSelectedLayerId(layers[0].id)
    }
  }, [layers, selectedLayerId])

  useEffect(() => {
    fetchAEG()
  }, [fetchAEG])

  useEffect(() => {
    if (!projectId) return undefined

    const intervalId = window.setInterval(() => {
      fetchAEG({ silent: true })
    }, 4000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [projectId, fetchAEG])

  const openFocusedGraph = () => {
    if (!isLoading && !error && nodes.length > 0) {
      setIsFocused(true)
    }
  }

  const closeFocusedGraph = () => {
    setIsFocused(false)
  }

  const renderGraph = ({ className }) => (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={(_, node) => {
        const clickedId = node?.id || null
        setSelectedLayerId(clickedId)
        onNodeSelect?.(clickedId)
      }}
      onPaneClick={() => {
        onNodeSelect?.(null)
      }}
      nodeTypes={nodeTypes}
      fitView
      minZoom={0.5}
      maxZoom={1.5}
      className={className}
    >
      <Background color="#f1e7d9" gap={16} />
      <Controls className="bg-card/90 border border-primary/40 rounded-lg shadow-lg" />
    </ReactFlow>
  )

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center border border-dashed border-border bg-secondary/40 p-4 text-sm text-foreground/60">
        Loading AEG...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-48 items-center justify-center border border-dashed border-border bg-secondary/40 p-4 text-sm text-destructive">
        {error}
      </div>
    )
  }

  const selectedLayer = layers.find((layer) => layer.id === selectedLayerId) || layers[0] || null
  const selectedBlackboardNotes = selectedLayer
    ? blackboardByLayer[selectedLayer.id] || []
    : []

  return (
    <>
      <style>{FLASH_ANIMATION}</style>
      <div className="overflow-hidden rounded-xl border-2 border-primary/40 bg-gradient-to-br from-card via-card to-secondary/50 shadow-xl">
        <div className="flex items-center justify-between border-b-2 border-primary/30 bg-gradient-to-r from-secondary/60 via-card/80 to-secondary/40 px-4 py-3 text-[11px]">
          <p className="font-semibold text-foreground">Project: <span className="mono text-primary/90">{graphMeta.projectName || projectId}</span></p>
          <p className="mono uppercase tracking-wider text-foreground/70">
            Live Agent Graph
          </p>
        </div>
        <div className="group relative h-[260px] min-h-[220px] border-b-2 border-primary/25 bg-gradient-to-b from-transparent to-card/20">
          {renderGraph({ className: 'h-full w-full' })}
          <button
            onClick={openFocusedGraph}
            className="absolute right-3 top-3 rounded-lg border-2 border-primary/50 bg-card/90 px-3 py-1.5 text-[11px] font-semibold text-foreground backdrop-blur-md transition hover:border-primary/70 hover:bg-card shadow-lg"
            aria-label="Open focused AEG preview"
          >
            Focus
          </button>
        </div>

        <div className="space-y-3 p-4">
          <div className="flex items-center justify-between">
            <p className="mono text-[10px] uppercase tracking-[0.18em] text-foreground/65">Layer Blackboard</p>
            {selectedLayer ? (
              <span className="mono text-[10px] font-semibold uppercase tracking-[0.12em] text-primary/85">
                {selectedLayer.title}
              </span>
            ) : null}
          </div>

          {selectedLayer ? (
            <div className="rounded-xl border border-primary/30 bg-card/70 p-3">
              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                {selectedLayer.agents.length > 0 ? (
                  selectedLayer.agents.map((agent) => (
                    <span
                      key={`${selectedLayer.id}-${agent}`}
                      className="inline-flex items-center rounded-full border border-border bg-secondary/70 px-2 py-0.5 text-[10px] font-medium text-foreground/75"
                    >
                      {titleCaseText(agent)}
                    </span>
                  ))
                ) : (
                  <span className="text-[11px] text-foreground/60">No layer agents found in task ledger.</span>
                )}
              </div>

              {selectedBlackboardNotes.length > 0 ? (
                <ul className="space-y-1.5 text-xs text-foreground/75">
                  {selectedBlackboardNotes.map((note, index) => (
                    <li key={`${selectedLayer.id}-note-${index}`} className="rounded-lg border border-border/80 bg-secondary/50 px-2.5 py-1.5">
                      {note}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="rounded-lg border border-dashed border-border/80 bg-secondary/35 px-3 py-2 text-xs text-foreground/60">
                  No blackboard notes for this layer yet.
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-border p-3 text-xs text-foreground/60">
              Select a layer in AEG to inspect blackboard activity.
            </div>
          )}
        </div>

        {isFocused &&
          typeof document !== 'undefined' &&
          createPortal(
            <div className="fixed inset-0 z-[120] flex items-center justify-center bg-midnight/75 p-4 backdrop-blur-sm">
              <button
                aria-label="Close focused AEG preview"
                className="absolute inset-0"
                onClick={closeFocusedGraph}
              />
              <div className="relative flex h-[92vh] w-full max-w-[96vw] flex-col rounded-2xl border-2 border-primary/40 bg-gradient-to-br from-card via-card to-secondary/50 p-6 shadow-2xl">
                <div className="mb-4 flex items-center justify-between border-b-2 border-primary/25 pb-3">
                  <p className="text-sm font-bold text-primary">Focused AEG Preview</p>
                  <button
                    onClick={closeFocusedGraph}
                    className="rounded-lg border-2 border-primary/50 bg-secondary/60 px-4 py-1.5 text-xs font-semibold text-foreground transition hover:border-primary/70 hover:bg-secondary"
                  >
                    Close
                  </button>
                </div>
                <div className="min-h-0 flex-1 rounded-xl border-2 border-primary/30 shadow-inner">
                  {renderGraph({ className: 'h-full w-full' })}
                </div>
              </div>
            </div>,
            document.body
          )}
      </div>
    </>
  )
}