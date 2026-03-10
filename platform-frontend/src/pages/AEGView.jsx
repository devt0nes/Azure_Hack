import { useEffect, useState, useCallback } from 'react'
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

function normalizeLedgerGraph(payload) {
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

    return {
      id: agent,
      type: 'default',
      position: positionByAgent[agent],
      data: {
        label: (
          <div className="text-left leading-tight">
            <div className="font-semibold text-[11px]">{titleCaseAgent(agent)}</div>
            <div className="mono text-[9px] uppercase tracking-wider mt-1 text-white/85">
              Group {groupLevel + 1}
            </div>
            <div className="text-[9px] mt-1 text-white/85">Handoffs: {outgoingCount}</div>
          </div>
        ),
      },
      style: {
        background: STATE_COLORS.PENDING,
        color: '#ffffff',
        border: '2px solid #f26a2e',
        borderRadius: '12px',
        padding: '12px 14px',
        fontSize: '11px',
        width: 190,
      },
    }
  })

  const flowEdges = []
  Object.entries(dependencies).forEach(([source, targets]) => {
    ;(targets || []).forEach((target) => {
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

function toFlowGraph(payload) {
  if (Array.isArray(payload?.nodes) && Array.isArray(payload?.edges)) {
    return normalizeLegacyGraph(payload)
  }

  if (payload?.agent_specifications) {
    return normalizeLedgerGraph(payload)
  }

  throw new Error('Unsupported AEG payload format')
}

export default function AEGView({ projectId }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [graphMeta, setGraphMeta] = useState({ projectName: '', source: '' })
  const [isFocused, setIsFocused] = useState(false)

  const fetchAEG = useCallback(async () => {
    if (!projectId) {
      setNodes([])
      setEdges([])
      setGraphMeta({ projectName: '', source: '' })
      setError('No project selected yet.')
      setIsLoading(false)
      return
    }

    try {
      setIsLoading(true)
      setError('')
      const data = await getAEG({ projectId })
      const { flowNodes, flowEdges } = toFlowGraph(data)

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
      setIsLoading(false)
    }
  }, [projectId, setNodes, setEdges])

  useEffect(() => {
    fetchAEG()
  }, [fetchAEG])

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
      nodeTypes={nodeTypes}
      fitView
      minZoom={0.5}
      maxZoom={1.5}
      className={className}
    >
      <Background color="#f1e7d9" gap={16} />
      <Controls className="bg-white/90 border border-ink/10 rounded-lg" />
      <MiniMap
        nodeColor={(node) => node.style?.background || '#1c1c24'}
        className="bg-white/90 border border-ink/10 rounded-lg"
        maskColor="rgba(247, 241, 234, 0.6)"
      />
    </ReactFlow>
  )

  if (isLoading) {
    return (
      <div className="mt-3 h-48 rounded-xl border border-dashed border-ink/20 bg-white/60 p-4 text-sm text-ink/60 flex items-center justify-center">
        Loading AEG...
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-3 h-48 rounded-xl border border-dashed border-ink/20 bg-white/60 p-4 text-sm text-red-600 flex items-center justify-center">
        {error}
      </div>
    )
  }

  return (
    <div className="mt-3 rounded-xl border border-ink/20 bg-white overflow-hidden">
      <div className="flex items-center justify-between border-b border-ink/10 bg-sand/30 px-3 py-2 text-[11px]">
        <p className="text-ink/70">Project: {graphMeta.projectName || projectId}</p>
        <p className="uppercase tracking-wider text-ink/50">
          Source: Backend API
        </p>
      </div>
      <div className="group relative h-[300px] min-h-[260px]">
        {renderGraph({ className: 'h-full w-full' })}
        <button
          onClick={openFocusedGraph}
          className="absolute inset-0 rounded-b-xl border border-transparent bg-transparent"
          aria-label="Open focused AEG preview"
        />
        <div className="pointer-events-none absolute right-3 top-3 rounded-full bg-midnight/80 px-3 py-1 text-[11px] font-medium text-sand opacity-0 transition group-hover:opacity-100">
          Click to focus
        </div>
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
            <div className="relative flex h-[92vh] w-full max-w-[96vw] flex-col rounded-2xl border border-ink/20 bg-white p-6 shadow-2xl">
              <div className="mb-4 flex items-center justify-between">
                <p className="text-sm font-semibold text-ink/70">Focused AEG Preview</p>
                <button
                  onClick={closeFocusedGraph}
                  className="rounded-md bg-ink/5 px-3 py-1.5 text-xs font-medium text-ink/70 transition hover:bg-ink/10"
                >
                  Close
                </button>
              </div>
              <div className="min-h-0 flex-1 rounded-lg border border-ink/10">
                {renderGraph({ className: 'h-full w-full' })}
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  )
}
