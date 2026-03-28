import { useEffect, useState, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { getAEG } from '../services/api.js'

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

function titleCaseAgent(agentName) {
  return agentName
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function normalizeLegacyGraph(payload) {
  const nodes = Array.isArray(payload?.nodes) ? payload.nodes : []
  const edges = Array.isArray(payload?.edges) ? payload.edges : []

  const flowNodes = nodes.map((node, index) => ({
    id: node.id,
    type: 'default',
    data: {
      label: (
        <div className="text-center">
          <div className="font-semibold text-xs">{node.agent_type || node.id}</div>
          <div className="mono text-[9px] uppercase tracking-wider mt-1">
            {node.state || 'PENDING'}
          </div>
        </div>
      ),
    },
    position: { x: (index % 3) * 220, y: Math.floor(index / 3) * 130 },
    style: {
      background: STATE_COLORS[node.state] || '#1c1c24',
      color: node.state === 'PENDING' ? '#f7f1ea' : '#ffffff',
      border: `2px solid ${STATE_COLORS[node.state] || '#1c1c24'}`,
      borderRadius: '12px',
      padding: '12px 16px',
      fontSize: '11px',
      width: 170,
    },
  }))

  const flowEdges = edges.map((edge) => ({
    id: `${edge.from}-${edge.to}`,
    source: edge.from,
    target: edge.to,
    animated: true,
    style: { stroke: '#f26a2e', strokeWidth: 2 },
  }))

  return { flowNodes, flowEdges }
}

function normalizeLedgerGraph(payload, agentStatusMap = {}) {
  const specs = payload?.agent_specifications || {}
  const requiredAgents = Array.isArray(specs.required_agents) ? specs.required_agents : []
  const dependencies = specs.agent_dependencies || {}
  const executionGroups = Array.isArray(specs.parallel_execution_groups)
    ? specs.parallel_execution_groups
    : []

  const groupIndexByAgent = {}
  executionGroups.forEach((group, index) => {
    group.forEach((agent) => {
      groupIndexByAgent[agent] = index
    })
  })

  const agents =
    requiredAgents.length > 0
      ? requiredAgents
      : Array.from(
        new Set([
          ...Object.keys(dependencies),
          ...Object.values(dependencies).flatMap((value) => value || []),
        ])
      )

  const groupedAgents = executionGroups.length
    ? executionGroups
    : [agents.filter((agent) => agent in dependencies), agents.filter((agent) => !(agent in dependencies))]

  const positionByAgent = {}
  groupedAgents.forEach((group, groupIdx) => {
    const yStart = 40
    group.forEach((agent, idx) => {
      positionByAgent[agent] = {
        x: groupIdx * 260 + 30,
        y: yStart + idx * 130,
      }
    })
  })

  const ungrouped = agents.filter((agent) => !positionByAgent[agent])
  ungrouped.forEach((agent, idx) => {
    positionByAgent[agent] = {
      x: groupedAgents.length * 260 + 30,
      y: 40 + idx * 130,
    }
  })

  const flowNodes = agents.map((agent) => {
    const groupLevel = groupIndexByAgent[agent] ?? groupedAgents.length
    const outgoingCount = (dependencies[agent] || []).length
    const agentStatus = agentStatusMap[agent] || {}
    const progress = Math.max(0, Math.min(100, Math.round(agentStatus.progress ?? 0)))
    const state = agentStatus.state || 'PENDING'
    const isRunning = state === 'RUNNING'

    return {
      id: agent,
      type: 'default',
      position: positionByAgent[agent],
      data: {
        label: (
          <div className="text-left leading-tight">
            <div className="font-semibold text-[11px]">{titleCaseAgent(agent)}</div>
            <div className="mono text-[10px] font-bold mt-1">{progress}%</div>
            <div className={`mono text-[8px] uppercase tracking-wider mt-1 ${isRunning ? 'text-amber-200 font-semibold' : 'text-white/85'
              }`}>
              {state}
            </div>
            <div className="text-[8px] mt-1 text-white/75">Handoffs: {outgoingCount}</div>
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
        width: 190,
        boxShadow: isRunning
          ? '0 0 16px rgba(242, 106, 46, 0.8), inset 0 0 8px rgba(242, 106, 46, 0.3)'
          : '0 2px 8px rgba(0, 0, 0, 0.5)',
        outline: `1px solid ${STATE_COLORS[state]}40`,
      },
      className: isRunning ? 'node-running' : '',
    }
  })

  const flowEdges = []
  Object.entries(dependencies).forEach(([source, targets]) => {
    ; (targets || []).forEach((target) => {
      flowEdges.push({
        id: `${source}-${target}`,
        source,
        target,
        animated: true,
        style: { stroke: '#f26a2e', strokeWidth: 2 },
      })
    })
  })

  return { flowNodes, flowEdges }
}

function toFlowGraph(payload, agentStatusMap = {}) {
  if (Array.isArray(payload?.nodes) && Array.isArray(payload?.edges)) {
    return normalizeLegacyGraph(payload)
  }

  if (payload?.agent_specifications) {
    return normalizeLedgerGraph(payload, agentStatusMap)
  }

  throw new Error('Unsupported AEG payload format')
}

export default function AEGView({ projectId, onNodeSelect, agents = [] }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [graphMeta, setGraphMeta] = useState({ projectName: '', source: '' })
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
      const data = await getAEG({ projectId })
      const { flowNodes, flowEdges } = toFlowGraph(data, agentStatusMap)

      setNodes(flowNodes)
      setEdges(flowEdges)
      setGraphMeta({
        projectName: data?.project_name || data?.projectId || projectId,
        source: 'api',
      })
    } catch (fetchError) {
      console.error(fetchError)
      setError('Unable to load AEG. Ensure backend is running and a project exists.')
      setNodes([])
      setEdges([])
      setGraphMeta({ projectName: '', source: '' })
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
    }
  }, [projectId, setNodes, setEdges, agentStatusMap])

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
      onNodeClick={(_, node) => onNodeSelect?.(node?.id || null)}
      onPaneClick={() => onNodeSelect?.(null)}
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
        <div className="group relative h-[300px] min-h-[260px] border-b-2 border-primary/25 bg-gradient-to-b from-transparent to-card/20">
          {renderGraph({ className: 'h-full w-full' })}
          <button
            onClick={openFocusedGraph}
            className="absolute right-3 top-3 rounded-lg border-2 border-primary/50 bg-card/90 px-3 py-1.5 text-[11px] font-semibold text-foreground backdrop-blur-md transition hover:border-primary/70 hover:bg-card shadow-lg"
            aria-label="Open focused AEG preview"
          >
            Focus
          </button>
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
