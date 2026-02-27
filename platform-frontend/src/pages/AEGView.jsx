import { useEffect, useState, useCallback } from 'react'
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

export default function AEGView({ projectId = 'demo-project' }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchAEG = useCallback(async () => {
    // Skip fetch if no API URL is configured
    if (!import.meta.env.VITE_API_BASE_URL) {
      setIsLoading(false)
      setError('API not configured (set VITE_API_BASE_URL)')
      return
    }

    try {
      setIsLoading(true)
      setError('')
      const data = await getAEG({ projectId })

      const flowNodes = data.nodes.map((node, index) => ({
        id: node.id,
        type: 'default',
        data: {
          label: (
            <div className="text-center">
              <div className="font-semibold text-xs">{node.agent_type}</div>
              <div className="mono text-[9px] uppercase tracking-wider mt-1">
                {node.state}
              </div>
            </div>
          ),
        },
        position: { x: (index % 3) * 180, y: Math.floor(index / 3) * 120 },
        style: {
          background: STATE_COLORS[node.state] || '#1c1c24',
          color: node.state === 'PENDING' ? '#f7f1ea' : '#ffffff',
          border: `2px solid ${STATE_COLORS[node.state] || '#1c1c24'}`,
          borderRadius: '12px',
          padding: '12px 16px',
          fontSize: '11px',
          width: 140,
        },
      }))

      const flowEdges = data.edges.map((edge) => ({
        id: `${edge.from}-${edge.to}`,
        source: edge.from,
        target: edge.to,
        animated: true,
        style: { stroke: '#f26a2e', strokeWidth: 2 },
      }))

      setNodes(flowNodes)
      setEdges(flowEdges)
    } catch (err) {
      setError('Unable to load AEG')
      console.error('AEG fetch failed:', err)
    } finally {
      setIsLoading(false)
    }
  }, [projectId, setNodes, setEdges])

  useEffect(() => {
    fetchAEG()
  }, [fetchAEG])

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
    <div className="mt-3 h-64 rounded-xl border border-ink/20 bg-white overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.5}
        maxZoom={1.5}
      >
        <Background color="#f1e7d9" gap={16} />
        <Controls className="bg-white/90 border border-ink/10 rounded-lg" />
        <MiniMap
          nodeColor={(node) => node.style?.background || '#1c1c24'}
          className="bg-white/90 border border-ink/10 rounded-lg"
          maskColor="rgba(247, 241, 234, 0.6)"
        />
      </ReactFlow>
    </div>
  )
}
