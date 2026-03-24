import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactFlow, {
    addEdge,
    Background,
    Controls,
    Handle,
    MiniMap,
    NodeResizer,
    Position,
    ReactFlowProvider,
    useEdgesState,
    useNodesState,
} from 'reactflow'
import 'reactflow/dist/style.css'
import CanvasToolbar from '../components/CanvasToolbar.jsx'
import { loadCanvas, saveCanvas, uploadCanvasFile } from '../services/api.js'

const EDGE_LABELS = ['related to', 'input for', 'depends on', 'inspires']

const CANVAS_API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function createNodeId(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function getStickyClasses(color) {
    if (color === 'pink') return 'bg-pink-100 border-pink-300'
    if (color === 'blue') return 'bg-blue-100 border-blue-300'
    return 'bg-yellow-100 border-yellow-300'
}

function getNodeCardLabel(node) {
    if (!node) return 'Unknown node'
    if (node.type === 'textNote') return `Text note: ${node.data?.content || '(empty)'}`
    if (node.type === 'imageNode') return `Image: ${node.data?.filename || 'uploaded image'}`
    if (node.type === 'fileNode') return `File: ${node.data?.filename || 'uploaded file'}`
    if (node.type === 'urlNode') return `URL: ${node.data?.url || ''}`
    if (node.type === 'stickyNote') return `Sticky note: ${node.data?.text || '(empty)'}`
    return node.data?.label || node.id
}

function resolveCanvasAssetUrl(url) {
    const value = String(url || '').trim()
    if (!value) return ''
    if (/^https?:\/\//i.test(value)) return value
    if (!CANVAS_API_BASE) return value
    return `${CANVAS_API_BASE}${value.startsWith('/') ? '' : '/'}${value}`
}

function sanitizeCanvasData(nodes, edges) {
    return {
        nodes: nodes.map((node) => {
            const data = { ...(node.data || {}) }
            delete data.onDelete
            return {
                id: node.id,
                type: node.type,
                position: node.position,
                width: node.width,
                height: node.height,
                data,
            }
        }),
        edges: edges.map((edge) => ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.label,
            type: edge.type,
            markerEnd: edge.markerEnd,
            data: edge.data || {},
        })),
    }
}

export function exportCanvasAsContext(canvasData) {
    const nodes = Array.isArray(canvasData?.nodes) ? canvasData.nodes : []
    const edges = Array.isArray(canvasData?.edges) ? canvasData.edges : []

    if (nodes.length === 0 && edges.length === 0) return ''

    const lines = ['Canvas context:']

    nodes.forEach((node) => {
        if (node.type === 'textNote') {
            lines.push(`- Text note: ${node.data?.content || '(empty)'}`)
        } else if (node.type === 'imageNode') {
            lines.push(`- Image: ${node.data?.filename || 'uploaded image'}`)
        } else if (node.type === 'fileNode') {
            lines.push(`- File: ${node.data?.filename || 'uploaded file'}`)
        } else if (node.type === 'urlNode') {
            lines.push(`- URL: ${node.data?.url || ''}`)
        } else if (node.type === 'stickyNote') {
            lines.push(`- Sticky note: ${node.data?.text || '(empty)'}`)
        }
    })

    const nodeMap = new Map(nodes.map((node) => [node.id, node]))
    edges.forEach((edge) => {
        const source = nodeMap.get(edge.source)
        const target = nodeMap.get(edge.target)
        const sourceLabel = source ? getNodeCardLabel(source).replace(/^.*?:\s*/, '') : edge.source
        const targetLabel = target ? getNodeCardLabel(target).replace(/^.*?:\s*/, '') : edge.target
        lines.push(`- Connection: ${sourceLabel} --[${edge.label || 'related to'}]--> ${targetLabel}`)
    })

    return lines.join('\n')
}

function BaseNodeCard({ children, onDelete, selected }) {
    return (
        <div
            className={`group relative rounded-2xl border bg-white/90 p-3 text-ink shadow-glass backdrop-blur-sm dark:border-border dark:bg-card/90 dark:text-foreground ${selected ? 'border-[#F26A2E]' : 'border-white/30'
                }`}
        >
            <button
                onClick={onDelete}
                className="absolute -right-2 -top-2 h-6 w-6 rounded-full border border-white/50 bg-white/95 text-xs font-semibold text-ink opacity-0 shadow-sm transition group-hover:opacity-100 hover:text-red-600 dark:border-border dark:bg-card dark:text-foreground"
            >
                ×
            </button>
            <Handle
                type="target"
                position={Position.Left}
                style={{ background: '#F26A2E', width: 10, height: 10 }}
            />
            {children}
            <Handle
                type="source"
                position={Position.Right}
                style={{ background: '#F26A2E', width: 10, height: 10 }}
            />
        </div>
    )
}

function TextNoteNode({ id, data, selected }) {
    return (
        <>
            <NodeResizer isVisible={selected} minWidth={180} minHeight={120} lineStyle={{ borderColor: '#F26A2E' }} handleStyle={{ backgroundColor: '#F26A2E' }} />
            <BaseNodeCard selected={selected} onDelete={() => data.onDelete?.(id)}>
                <textarea
                    value={data.content || ''}
                    onChange={(event) => data.onChange?.(id, { content: event.target.value })}
                    placeholder="Write note..."
                    className="h-full min-h-[90px] w-full resize-none rounded-xl border border-white/40 bg-white/70 p-2 text-sm text-ink outline-none dark:border-border dark:bg-secondary/50 dark:text-foreground"
                />
            </BaseNodeCard>
        </>
    )
}

function ImageNode({ id, data, selected }) {
    return (
        <BaseNodeCard selected={selected} onDelete={() => data.onDelete?.(id)}>
            <div className="w-[220px]">
                <div className="mb-2 text-xs font-semibold text-ink">{data.filename || 'Image'}</div>
                <img
                    src={data.url}
                    alt={data.filename || 'Canvas image'}
                    className="max-h-44 w-full rounded-xl border border-white/40 object-cover"
                />
            </div>
        </BaseNodeCard>
    )
}

function FileNode({ id, data, selected }) {
    return (
        <BaseNodeCard selected={selected} onDelete={() => data.onDelete?.(id)}>
            <div className="w-[220px]">
                <div className="flex items-center gap-2">
                    <span className="text-xl">📄</span>
                    <div>
                        <p className="text-sm font-semibold text-ink">{data.filename || 'File'}</p>
                        <p className="text-xs text-ink/70">{data.fileType || 'unknown'}</p>
                    </div>
                </div>
            </div>
        </BaseNodeCard>
    )
}

function URLNode({ id, data, selected }) {
    return (
        <BaseNodeCard selected={selected} onDelete={() => data.onDelete?.(id)}>
            <div className="w-[240px]">
                <p className="mb-1 text-xs uppercase tracking-wider text-ink/70">URL</p>
                <a
                    href={data.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sm font-medium text-[#F26A2E] underline break-all"
                >
                    {data.url}
                </a>
            </div>
        </BaseNodeCard>
    )
}

function StickyNoteNode({ id, data, selected }) {
    return (
        <div className={`group relative rounded-2xl border p-3 text-ink shadow-glass ${getStickyClasses(data.color)} ${selected ? 'ring-2 ring-[#F26A2E]' : ''}`}>
            <button
                onClick={() => data.onDelete?.(id)}
                className="absolute -right-2 -top-2 h-6 w-6 rounded-full border border-white/50 bg-white/95 text-xs font-semibold text-ink opacity-0 shadow-sm transition group-hover:opacity-100 hover:text-red-600 dark:border-border dark:bg-card dark:text-foreground"
            >
                ×
            </button>
            <Handle
                type="target"
                position={Position.Left}
                style={{ background: '#F26A2E', width: 10, height: 10 }}
            />
            <input
                value={data.text || ''}
                onChange={(event) => data.onChange?.(id, { text: event.target.value })}
                placeholder="Sticky text"
                className="w-[180px] rounded-md bg-transparent text-sm font-medium text-ink outline-none"
            />
            <Handle
                type="source"
                position={Position.Right}
                style={{ background: '#F26A2E', width: 10, height: 10 }}
            />
        </div>
    )
}

export default function IdeaCanvas({ projectId, isFullscreen = false }) {
    const [nodes, setNodes, onNodesChange] = useNodesState([])
    const [edges, setEdges, onEdgesChange] = useEdgesState([])
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState('')
    const [drawMode, setDrawMode] = useState(false)
    const [drawings, setDrawings] = useState([])
    const drawCanvasRef = useRef(null)
    const drawContainerRef = useRef(null)
    const liveStrokeRef = useRef(null)

    const withNodeHandlers = useCallback(
        (rawNodes) =>
            (rawNodes || []).map((node) => {
                const normalizedData =
                    node.type === 'imageNode' || node.type === 'fileNode'
                        ? {
                            ...(node.data || {}),
                            url: resolveCanvasAssetUrl(node.data?.url),
                        }
                        : { ...(node.data || {}) }

                return {
                    ...node,
                    data: {
                        ...normalizedData,
                        onDelete: (nodeId) => setNodes((prev) => prev.filter((item) => item.id !== nodeId)),
                        onChange: (nodeId, patch) =>
                            setNodes((prev) =>
                                prev.map((item) =>
                                    item.id === nodeId
                                        ? {
                                            ...item,
                                            data: { ...item.data, ...patch },
                                        }
                                        : item
                                )
                            ),
                    },
                }
            }),
        [setNodes]
    )

    const nodeTypes = useMemo(
        () => ({
            textNote: TextNoteNode,
            imageNode: ImageNode,
            fileNode: FileNode,
            urlNode: URLNode,
            stickyNote: StickyNoteNode,
        }),
        []
    )

    const addNode = useCallback(
        (node) => {
            setNodes((prev) => withNodeHandlers([...prev, node]))
        },
        [setNodes, withNodeHandlers]
    )

    const addTextNote = useCallback(() => {
        addNode({
            id: createNodeId('text'),
            type: 'textNote',
            position: { x: 120, y: 120 },
            data: { content: '' },
            style: { width: 240, height: 150 },
        })
    }, [addNode])

    const addStickyNote = useCallback(
        (color) => {
            addNode({
                id: createNodeId('sticky'),
                type: 'stickyNote',
                position: { x: 180, y: 200 },
                data: { color, text: 'New sticky' },
            })
        },
        [addNode]
    )

    const addUrlNode = useCallback(
        (url) => {
            addNode({
                id: createNodeId('url'),
                type: 'urlNode',
                position: { x: 240, y: 260 },
                data: { url },
            })
        },
        [addNode]
    )

    const addUploadedAssetNode = useCallback(
        async (file, nodeType) => {
            if (!projectId || !file) {
                setError('Select a project before uploading canvas assets.')
                return
            }

            try {
                setError('')
                const uploaded = await uploadCanvasFile({ projectId, file })
                const resolvedUrl = resolveCanvasAssetUrl(uploaded.url)
                if (nodeType === 'imageNode') {
                    addNode({
                        id: createNodeId('image'),
                        type: 'imageNode',
                        position: { x: 300, y: 140 },
                        data: {
                            url: resolvedUrl,
                            filename: uploaded.filename || file.name,
                        },
                    })
                    return
                }

                addNode({
                    id: createNodeId('file'),
                    type: 'fileNode',
                    position: { x: 320, y: 260 },
                    data: {
                        url: resolvedUrl,
                        filename: uploaded.filename || file.name,
                        fileType: file.type || 'unknown',
                    },
                })
            } catch (uploadError) {
                console.error(uploadError)
                setError('Failed to upload file to canvas.')
            }
        },
        [addNode, projectId]
    )

    const onConnect = useCallback(
        (connection) => {
            setEdges((prev) =>
                addEdge(
                    {
                        ...connection,
                        id: createNodeId('edge'),
                        label: EDGE_LABELS[0],
                        data: { labelIndex: 0 },
                        style: { stroke: '#F26A2E', strokeWidth: 2 },
                    },
                    prev
                )
            )
        },
        [setEdges]
    )

    const onEdgeClick = useCallback(
        (_event, edge) => {
            setEdges((prev) =>
                prev.map((item) => {
                    if (item.id !== edge.id) return item
                    const current = Number(item.data?.labelIndex || 0)
                    const next = (current + 1) % EDGE_LABELS.length
                    return {
                        ...item,
                        label: EDGE_LABELS[next],
                        data: { ...(item.data || {}), labelIndex: next },
                    }
                })
            )
        },
        [setEdges]
    )

    useEffect(() => {
        let cancelled = false

        async function fetchCanvas() {
            if (!projectId) {
                setNodes([])
                setEdges([])
                return
            }

            try {
                setIsLoading(true)
                setError('')
                const response = await loadCanvas({ projectId })
                const canvasData = response?.canvas_data || {}
                if (cancelled) return

                setNodes(withNodeHandlers(Array.isArray(canvasData.nodes) ? canvasData.nodes : []))
                setEdges(Array.isArray(canvasData.edges) ? canvasData.edges : [])
                setDrawings(Array.isArray(canvasData.drawings) ? canvasData.drawings : [])
            } catch (loadError) {
                console.error(loadError)
                if (!cancelled) {
                    setNodes([])
                    setEdges([])
                    setDrawings([])
                    setError('Unable to load Idea Canvas for this project.')
                }
            } finally {
                if (!cancelled) setIsLoading(false)
            }
        }

        fetchCanvas()
        return () => {
            cancelled = true
        }
    }, [projectId, setEdges, setNodes, withNodeHandlers])

    useEffect(() => {
        if (!projectId) return undefined

        const timer = window.setInterval(async () => {
            try {
                const canvasData = {
                    ...sanitizeCanvasData(nodes, edges),
                    drawings,
                }
                await saveCanvas({ projectId, canvasData })
            } catch (saveError) {
                console.error(saveError)
            }
        }, 30000)

        return () => window.clearInterval(timer)
    }, [projectId, nodes, edges, drawings])

    useEffect(() => {
        const canvas = drawCanvasRef.current
        const container = drawContainerRef.current
        if (!canvas || !container) return

        const rect = container.getBoundingClientRect()
        const width = Math.max(1, Math.floor(rect.width))
        const height = Math.max(1, Math.floor(rect.height))

        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width
            canvas.height = height
        }

        const ctx = canvas.getContext('2d')
        if (!ctx) return

        ctx.clearRect(0, 0, width, height)
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'

        drawings.forEach((stroke) => {
            const points = Array.isArray(stroke?.points) ? stroke.points : []
            if (points.length < 2) return
            ctx.beginPath()
            ctx.strokeStyle = '#F26A2E'
            ctx.lineWidth = 2
            ctx.moveTo(points[0].x * width, points[0].y * height)
            for (let index = 1; index < points.length; index += 1) {
                ctx.lineTo(points[index].x * width, points[index].y * height)
            }
            ctx.stroke()
        })
    }, [drawings, isFullscreen])

    const appendDrawingPoint = useCallback((event) => {
        const container = drawContainerRef.current
        if (!container || !liveStrokeRef.current) return
        const rect = container.getBoundingClientRect()
        if (!rect.width || !rect.height) return
        const x = (event.clientX - rect.left) / rect.width
        const y = (event.clientY - rect.top) / rect.height
        const safeX = Math.min(1, Math.max(0, x))
        const safeY = Math.min(1, Math.max(0, y))
        liveStrokeRef.current.points.push({ x: safeX, y: safeY })
    }, [])

    const onDrawPointerDown = useCallback(
        (event) => {
            if (!drawMode) return
            event.preventDefault()
            liveStrokeRef.current = { points: [] }
            setDrawings((prev) => [...prev, { points: [] }])
            appendDrawingPoint(event)
        },
        [appendDrawingPoint, drawMode]
    )

    const onDrawPointerMove = useCallback(
        (event) => {
            if (!drawMode || !liveStrokeRef.current) return
            event.preventDefault()
            appendDrawingPoint(event)
            setDrawings((prev) => {
                if (prev.length === 0) return [{ ...liveStrokeRef.current }]
                const draft = prev.slice()
                draft[draft.length - 1] = { ...liveStrokeRef.current }
                return draft
            })
        },
        [appendDrawingPoint, drawMode]
    )

    const onDrawPointerUp = useCallback(() => {
        const live = liveStrokeRef.current
        if (live && live.points.length > 1) {
            setDrawings((prev) => {
                const withoutDraft = prev.slice(0, -1)
                return [...withoutDraft, live]
            })
        } else if (live) {
            setDrawings((prev) => prev.slice(0, -1))
        }
        liveStrokeRef.current = null
    }, [])

    return (
        <div className={`${isFullscreen ? 'h-full space-y-3' : 'mt-3 space-y-3'}`}>
            <CanvasToolbar
                onAddTextNote={addTextNote}
                onAddStickyNote={addStickyNote}
                onUploadImage={(file) => addUploadedAssetNode(file, 'imageNode')}
                onUploadFile={(file) => addUploadedAssetNode(file, 'fileNode')}
                onAddUrl={addUrlNode}
                drawMode={drawMode}
                onToggleDrawMode={() => setDrawMode((prev) => !prev)}
                onClearDrawings={() => setDrawings([])}
                onClearCanvas={() => {
                    setNodes([])
                    setEdges([])
                    setDrawings([])
                }}
            />

            {error ? <p className="text-sm text-destructive">{error}</p> : null}

            <div
                ref={drawContainerRef}
                className={`${isFullscreen ? 'h-[calc(100%-64px)] min-h-[540px]' : 'h-[520px]'} relative overflow-hidden rounded-2xl border border-white/30 dark:border-border`}
                style={{
                    backgroundColor: 'hsl(var(--card) / 0.75)',
                    backgroundImage: 'radial-gradient(circle, hsl(var(--foreground) / 0.16) 1px, transparent 1px)',
                    backgroundSize: '20px 20px',
                }}
            >
                <ReactFlowProvider>
                    {isLoading ? (
                        <div className="flex h-full items-center justify-center text-sm text-ink/70">Loading canvas...</div>
                    ) : (
                        <ReactFlow
                            nodes={nodes}
                            edges={edges}
                            onNodesChange={onNodesChange}
                            onEdgesChange={onEdgesChange}
                            onConnect={onConnect}
                            onEdgeClick={onEdgeClick}
                            nodeTypes={nodeTypes}
                            fitView
                            deleteKeyCode={['Backspace', 'Delete']}
                            minZoom={0.4}
                            maxZoom={1.8}
                            className="h-full w-full"
                            nodesDraggable={!drawMode}
                            nodesConnectable={!drawMode}
                            elementsSelectable={!drawMode}
                            panOnDrag={!drawMode}
                            defaultEdgeOptions={{
                                style: { stroke: '#F26A2E', strokeWidth: 2 },
                                labelStyle: { fill: 'hsl(var(--foreground))', fontSize: 11, fontWeight: 600 },
                                labelBgStyle: { fill: 'hsl(var(--card))', fillOpacity: 0.9 },
                            }}
                        >
                            <Background color="hsl(var(--wire))" gap={16} />
                            <Controls className="bg-card/90 border border-border rounded-lg" />
                            <MiniMap
                                nodeColor={() => 'hsl(var(--card))'}
                                className="bg-card/90 border border-border rounded-lg"
                                maskColor="hsl(var(--background) / 0.6)"
                            />
                        </ReactFlow>
                    )}

                    <canvas
                        ref={drawCanvasRef}
                        className={`absolute inset-0 z-20 ${drawMode ? 'cursor-crosshair pointer-events-auto' : 'pointer-events-none'}`}
                        onPointerDown={onDrawPointerDown}
                        onPointerMove={onDrawPointerMove}
                        onPointerUp={onDrawPointerUp}
                        onPointerLeave={onDrawPointerUp}
                    />
                </ReactFlowProvider>
            </div>
        </div>
    )
}
