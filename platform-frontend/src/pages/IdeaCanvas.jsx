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
const LOCAL_CANVAS_DRAFT_KEY = 'idea-canvas-draft-v1'

const CANVAS_API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function createNodeId(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function getStickyClasses(color) {
    if (color === 'pink') return 'bg-pink-100 border-pink-300'
    if (color === 'blue') return 'bg-blue-100 border-blue-300'
    return 'bg-yellow-100 border-yellow-300'
}

function normalizeDrawing(drawing) {
    if (!drawing || typeof drawing !== 'object') return null

    if (drawing.kind === 'shape') {
        const start = drawing.start
        const end = drawing.end
        if (!start || !end) return null
        const allowedShapes = new Set([
            'rectangle',
            'roundedRectangle',
            'square',
            'circle',
            'ellipse',
            'triangle',
            'diamond',
            'pentagon',
            'hexagon',
            'octagon',
            'line',
            'arrow',
            'star',
        ])
        if (!allowedShapes.has(drawing.shape)) return null
        return {
            kind: 'shape',
            shape: drawing.shape,
            start,
            end,
        }
    }

    const points = Array.isArray(drawing.points) ? drawing.points : []
    if (points.length < 2) return null
    return {
        kind: 'path',
        tool: drawing.tool === 'eraser' ? 'eraser' : 'pen',
        points,
    }
}

function drawPolygon(ctx, points) {
    if (!Array.isArray(points) || points.length < 3) return
    ctx.beginPath()
    ctx.moveTo(points[0][0], points[0][1])
    for (let index = 1; index < points.length; index += 1) {
        ctx.lineTo(points[index][0], points[index][1])
    }
    ctx.closePath()
    ctx.stroke()
}

function polygonPoints(cx, cy, radius, sides, rotation = -Math.PI / 2) {
    return Array.from({ length: sides }, (_, index) => {
        const angle = rotation + (index * Math.PI * 2) / sides
        return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)]
    })
}

function drawStar(ctx, cx, cy, outerRadius, innerRadius, points = 5) {
    const starPoints = []
    for (let index = 0; index < points * 2; index += 1) {
        const angle = -Math.PI / 2 + (index * Math.PI) / points
        const radius = index % 2 === 0 ? outerRadius : innerRadius
        starPoints.push([cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)])
    }
    drawPolygon(ctx, starPoints)
}

function drawShape(ctx, shape, startX, startY, endX, endY) {
    const minX = Math.min(startX, endX)
    const minY = Math.min(startY, endY)
    const width = Math.abs(endX - startX)
    const height = Math.abs(endY - startY)
    const centerX = minX + width / 2
    const centerY = minY + height / 2
    const radius = Math.min(width, height) / 2

    if (shape === 'line' || shape === 'arrow') {
        ctx.beginPath()
        ctx.moveTo(startX, startY)
        ctx.lineTo(endX, endY)
        ctx.stroke()

        if (shape === 'arrow') {
            const headLength = 12
            const angle = Math.atan2(endY - startY, endX - startX)
            ctx.beginPath()
            ctx.moveTo(endX, endY)
            ctx.lineTo(endX - headLength * Math.cos(angle - Math.PI / 7), endY - headLength * Math.sin(angle - Math.PI / 7))
            ctx.moveTo(endX, endY)
            ctx.lineTo(endX - headLength * Math.cos(angle + Math.PI / 7), endY - headLength * Math.sin(angle + Math.PI / 7))
            ctx.stroke()
        }
        return
    }

    if (shape === 'rectangle') {
        ctx.strokeRect(minX, minY, width, height)
        return
    }

    if (shape === 'roundedRectangle') {
        const corner = Math.min(14, width / 4, height / 4)
        ctx.beginPath()
        ctx.moveTo(minX + corner, minY)
        ctx.lineTo(minX + width - corner, minY)
        ctx.quadraticCurveTo(minX + width, minY, minX + width, minY + corner)
        ctx.lineTo(minX + width, minY + height - corner)
        ctx.quadraticCurveTo(minX + width, minY + height, minX + width - corner, minY + height)
        ctx.lineTo(minX + corner, minY + height)
        ctx.quadraticCurveTo(minX, minY + height, minX, minY + height - corner)
        ctx.lineTo(minX, minY + corner)
        ctx.quadraticCurveTo(minX, minY, minX + corner, minY)
        ctx.closePath()
        ctx.stroke()
        return
    }

    if (shape === 'square') {
        const side = Math.min(width, height)
        ctx.strokeRect(minX, minY, side, side)
        return
    }

    if (shape === 'circle') {
        ctx.beginPath()
        ctx.ellipse(centerX, centerY, radius, radius, 0, 0, Math.PI * 2)
        ctx.stroke()
        return
    }

    if (shape === 'ellipse') {
        ctx.beginPath()
        ctx.ellipse(centerX, centerY, width / 2, height / 2, 0, 0, Math.PI * 2)
        ctx.stroke()
        return
    }

    if (shape === 'triangle') {
        drawPolygon(ctx, [
            [centerX, minY],
            [minX + width, minY + height],
            [minX, minY + height],
        ])
        return
    }

    if (shape === 'diamond') {
        drawPolygon(ctx, [
            [centerX, minY],
            [minX + width, centerY],
            [centerX, minY + height],
            [minX, centerY],
        ])
        return
    }

    if (shape === 'pentagon') {
        drawPolygon(ctx, polygonPoints(centerX, centerY, radius, 5))
        return
    }

    if (shape === 'hexagon') {
        drawPolygon(ctx, polygonPoints(centerX, centerY, radius, 6, 0))
        return
    }

    if (shape === 'octagon') {
        drawPolygon(ctx, polygonPoints(centerX, centerY, radius, 8))
        return
    }

    if (shape === 'star') {
        drawStar(ctx, centerX, centerY, radius, Math.max(radius * 0.45, 4), 5)
    }
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

function readLocalCanvasDraft() {
    try {
        if (typeof window === 'undefined') return null
        const raw = window.localStorage.getItem(LOCAL_CANVAS_DRAFT_KEY)
        if (!raw) return null
        const parsed = JSON.parse(raw)
        if (!parsed || typeof parsed !== 'object') return null
        return {
            nodes: Array.isArray(parsed.nodes) ? parsed.nodes : [],
            edges: Array.isArray(parsed.edges) ? parsed.edges : [],
            drawings: Array.isArray(parsed.drawings) ? parsed.drawings : [],
        }
    } catch {
        return null
    }
}

function writeLocalCanvasDraft(canvasData) {
    try {
        if (typeof window === 'undefined' || !canvasData) return
        window.localStorage.setItem(LOCAL_CANVAS_DRAFT_KEY, JSON.stringify(canvasData))
    } catch {
    }
}

function clearLocalCanvasDraft() {
    try {
        if (typeof window === 'undefined') return
        window.localStorage.removeItem(LOCAL_CANVAS_DRAFT_KEY)
    } catch {
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
                className="w-[180px] rounded-md bg-transparent text-sm font-medium text-black outline-none placeholder:text-black/70 dark:text-black dark:placeholder:text-black/70"
            />
            <Handle
                type="source"
                position={Position.Right}
                style={{ background: '#F26A2E', width: 10, height: 10 }}
            />
        </div>
    )
}

export default function IdeaCanvas({ projectId, isFullscreen = false, onSaveStatusChange }) {
    const [nodes, setNodes, onNodesChange] = useNodesState([])
    const [edges, setEdges, onEdgesChange] = useEdgesState([])
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState('')
    const [drawMode, setDrawMode] = useState(false)
    const [drawTool, setDrawTool] = useState('pen')
    const [shapeType, setShapeType] = useState('rectangle')
    const [drawings, setDrawings] = useState([])
    const drawCanvasRef = useRef(null)
    const drawContainerRef = useRef(null)
    const miniDrawingsCanvasRef = useRef(null)
    const liveStrokeRef = useRef(null)
    const hasHydratedRef = useRef(false)
    const saveTimerRef = useRef(null)
    const lastSavedFingerprintRef = useRef('')
    const latestCanvasSnapshotRef = useRef({ projectId: '', canvasData: null })
    const migratedLocalDraftRef = useRef(false)
    const hydrationPendingRef = useRef(false)
    const hydrationFingerprintRef = useRef('')

    const reportSaveState = useCallback(
        (state) => {
            if (typeof onSaveStatusChange === 'function') {
                onSaveStatusChange(state)
            }
        },
        [onSaveStatusChange]
    )

    const persistCanvas = useCallback(
        async (payloadProjectId, payloadCanvasData) => {
            if (!payloadProjectId || !payloadCanvasData) return
            const fingerprint = JSON.stringify(payloadCanvasData)
            if (fingerprint === lastSavedFingerprintRef.current) return
            await saveCanvas({ projectId: payloadProjectId, canvasData: payloadCanvasData })
            lastSavedFingerprintRef.current = fingerprint
        },
        []
    )

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
        hasHydratedRef.current = false
        migratedLocalDraftRef.current = false
        hydrationPendingRef.current = false
        hydrationFingerprintRef.current = ''

        async function fetchCanvas() {
            if (!projectId) {
                const localDraft = readLocalCanvasDraft() || { nodes: [], edges: [], drawings: [] }
                const localFingerprint = JSON.stringify(localDraft)
                setNodes(withNodeHandlers(localDraft.nodes))
                setEdges(localDraft.edges)
                setDrawings(localDraft.drawings)
                latestCanvasSnapshotRef.current = { projectId: '', canvasData: localDraft }
                lastSavedFingerprintRef.current = localFingerprint
                hydrationPendingRef.current = true
                hydrationFingerprintRef.current = localFingerprint
                hasHydratedRef.current = true
                reportSaveState('saved')
                return
            }

            try {
                setIsLoading(true)
                setError('')
                const response = await loadCanvas({ projectId })
                const canvasData = response?.canvas_data || {}
                if (cancelled) return

                let hydratedCanvasData = {
                    nodes: Array.isArray(canvasData.nodes) ? canvasData.nodes : [],
                    edges: Array.isArray(canvasData.edges) ? canvasData.edges : [],
                    drawings: Array.isArray(canvasData.drawings) ? canvasData.drawings : [],
                }

                const hasServerContent =
                    hydratedCanvasData.nodes.length > 0 ||
                    hydratedCanvasData.edges.length > 0 ||
                    hydratedCanvasData.drawings.length > 0

                const localDraft = readLocalCanvasDraft()
                const hasLocalDraft =
                    !!localDraft &&
                    (localDraft.nodes.length > 0 || localDraft.edges.length > 0 || localDraft.drawings.length > 0)

                if (!hasServerContent && hasLocalDraft && !migratedLocalDraftRef.current) {
                    hydratedCanvasData = localDraft
                    migratedLocalDraftRef.current = true
                }

                setNodes(withNodeHandlers(hydratedCanvasData.nodes))
                setEdges(hydratedCanvasData.edges)
                setDrawings(hydratedCanvasData.drawings)
                const hydratedFingerprint = JSON.stringify(hydratedCanvasData)
                latestCanvasSnapshotRef.current = { projectId, canvasData: hydratedCanvasData }
                lastSavedFingerprintRef.current = hydratedFingerprint
                hydrationPendingRef.current = true
                hydrationFingerprintRef.current = hydratedFingerprint
                hasHydratedRef.current = true
                reportSaveState('saved')
            } catch (loadError) {
                console.error(loadError)
                if (!cancelled) {
                    setNodes([])
                    setEdges([])
                    setDrawings([])
                    setError('Unable to load Idea Canvas for this project.')
                    latestCanvasSnapshotRef.current = {
                        projectId,
                        canvasData: { nodes: [], edges: [], drawings: [] },
                    }
                    lastSavedFingerprintRef.current = JSON.stringify({ nodes: [], edges: [], drawings: [] })
                    hasHydratedRef.current = true
                    hydrationPendingRef.current = false
                    hydrationFingerprintRef.current = ''
                    reportSaveState('error')
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
        if (!hasHydratedRef.current) return undefined

        const canvasData = {
            ...sanitizeCanvasData(nodes, edges),
            drawings,
        }

        const fingerprint = JSON.stringify(canvasData)

        if (hydrationPendingRef.current) {
            if (fingerprint !== hydrationFingerprintRef.current) {
                return undefined
            }
            hydrationPendingRef.current = false
            hydrationFingerprintRef.current = ''
            latestCanvasSnapshotRef.current = { projectId, canvasData }
            return undefined
        }

        latestCanvasSnapshotRef.current = { projectId, canvasData }

        if (fingerprint !== lastSavedFingerprintRef.current) {
            reportSaveState('unsaved')
        }

        if (saveTimerRef.current) {
            window.clearTimeout(saveTimerRef.current)
        }

        saveTimerRef.current = window.setTimeout(async () => {
            try {
                reportSaveState('saving')
                if (!projectId) {
                    writeLocalCanvasDraft(canvasData)
                    lastSavedFingerprintRef.current = fingerprint
                    reportSaveState('saved-local')
                } else {
                    await persistCanvas(projectId, canvasData)
                    const hasAnyContent =
                        canvasData.nodes.length > 0 ||
                        canvasData.edges.length > 0 ||
                        canvasData.drawings.length > 0
                    if (hasAnyContent) {
                        clearLocalCanvasDraft()
                    }
                    reportSaveState('saved')
                }
            } catch (saveError) {
                console.error(saveError)
                reportSaveState('error')
            }
        }, 1000)

        return () => {
            if (saveTimerRef.current) {
                window.clearTimeout(saveTimerRef.current)
                saveTimerRef.current = null
            }
        }
    }, [projectId, nodes, edges, drawings, persistCanvas])

    useEffect(() => {
        return () => {
            if (saveTimerRef.current) {
                window.clearTimeout(saveTimerRef.current)
                saveTimerRef.current = null
            }

            const snapshot = latestCanvasSnapshotRef.current
            if (!snapshot?.canvasData || !hasHydratedRef.current) return

            if (!snapshot.projectId) {
                writeLocalCanvasDraft(snapshot.canvasData)
                const localFingerprint = JSON.stringify(snapshot.canvasData)
                lastSavedFingerprintRef.current = localFingerprint
                reportSaveState('saved-local')
                return
            }

            reportSaveState('saving')
            persistCanvas(snapshot.projectId, snapshot.canvasData)
                .then(() => {
                    const hasAnyContent =
                        snapshot.canvasData.nodes.length > 0 ||
                        snapshot.canvasData.edges.length > 0 ||
                        snapshot.canvasData.drawings.length > 0
                    if (hasAnyContent) {
                        clearLocalCanvasDraft()
                    }
                    reportSaveState('saved')
                })
                .catch((saveError) => {
                    console.error(saveError)
                    reportSaveState('error')
                })
        }
    }, [persistCanvas, reportSaveState])

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

        drawings.forEach((entry) => {
            const drawing = normalizeDrawing(entry)
            if (!drawing) return

            if (drawing.kind === 'shape') {
                const startX = drawing.start.x * width
                const startY = drawing.start.y * height
                const endX = drawing.end.x * width
                const endY = drawing.end.y * height

                ctx.save()
                ctx.globalCompositeOperation = 'source-over'
                ctx.strokeStyle = '#F26A2E'
                ctx.lineWidth = 2

                drawShape(ctx, drawing.shape, startX, startY, endX, endY)

                ctx.restore()
                return
            }

            const points = drawing.points
            ctx.save()
            if (drawing.tool === 'eraser') {
                ctx.globalCompositeOperation = 'destination-out'
                ctx.strokeStyle = 'rgba(0, 0, 0, 1)'
                ctx.lineWidth = 18
            } else {
                ctx.globalCompositeOperation = 'source-over'
                ctx.strokeStyle = '#F26A2E'
                ctx.lineWidth = 2
            }

            ctx.beginPath()
            ctx.moveTo(points[0].x * width, points[0].y * height)
            for (let index = 1; index < points.length; index += 1) {
                ctx.lineTo(points[index].x * width, points[index].y * height)
            }
            ctx.stroke()
            ctx.restore()
        })
    }, [drawings, isFullscreen])

    useEffect(() => {
        const miniCanvas = miniDrawingsCanvasRef.current
        if (!miniCanvas) return
        const width = miniCanvas.width
        const height = miniCanvas.height
        const ctx = miniCanvas.getContext('2d')
        if (!ctx) return

        ctx.clearRect(0, 0, width, height)
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'

        drawings.forEach((entry) => {
            const drawing = normalizeDrawing(entry)
            if (!drawing) return

            if (drawing.kind === 'shape') {
                const startX = drawing.start.x * width
                const startY = drawing.start.y * height
                const endX = drawing.end.x * width
                const endY = drawing.end.y * height
                ctx.save()
                ctx.globalCompositeOperation = 'source-over'
                ctx.strokeStyle = '#F26A2E'
                ctx.lineWidth = 1.5
                drawShape(ctx, drawing.shape, startX, startY, endX, endY)
                ctx.restore()
                return
            }

            const points = drawing.points
            ctx.save()
            if (drawing.tool === 'eraser') {
                ctx.globalCompositeOperation = 'destination-out'
                ctx.strokeStyle = 'rgba(0, 0, 0, 1)'
                ctx.lineWidth = 8
            } else {
                ctx.globalCompositeOperation = 'source-over'
                ctx.strokeStyle = '#F26A2E'
                ctx.lineWidth = 1.5
            }
            ctx.beginPath()
            ctx.moveTo(points[0].x * width, points[0].y * height)
            for (let index = 1; index < points.length; index += 1) {
                ctx.lineTo(points[index].x * width, points[index].y * height)
            }
            ctx.stroke()
            ctx.restore()
        })
    }, [drawings])

    const getNormalizedPointFromEvent = useCallback((event) => {
        const container = drawContainerRef.current
        if (!container) return null
        const rect = container.getBoundingClientRect()
        if (!rect.width || !rect.height) return null
        const x = (event.clientX - rect.left) / rect.width
        const y = (event.clientY - rect.top) / rect.height
        return {
            x: Math.min(1, Math.max(0, x)),
            y: Math.min(1, Math.max(0, y)),
        }
    }, [])

    const appendDrawingPoint = useCallback((event) => {
        if (!liveStrokeRef.current) return
        const point = getNormalizedPointFromEvent(event)
        if (!point) return
        if (!Array.isArray(liveStrokeRef.current.points)) {
            liveStrokeRef.current.points = []
        }
        liveStrokeRef.current.points.push(point)
    }, [getNormalizedPointFromEvent])

    const onDrawPointerDown = useCallback(
        (event) => {
            if (!drawMode) return
            event.preventDefault()
            if (drawTool === 'shape') {
                const point = getNormalizedPointFromEvent(event)
                if (!point) return
                liveStrokeRef.current = {
                    kind: 'shape',
                    shape: shapeType,
                    start: point,
                    end: point,
                }
                setDrawings((prev) => [...prev, { ...liveStrokeRef.current }])
                return
            }

            liveStrokeRef.current = {
                kind: 'path',
                tool: drawTool === 'eraser' ? 'eraser' : 'pen',
                points: [],
            }
            setDrawings((prev) => [...prev, { ...liveStrokeRef.current }])
            appendDrawingPoint(event)
        },
        [appendDrawingPoint, drawMode, drawTool, getNormalizedPointFromEvent, shapeType]
    )

    const onDrawPointerMove = useCallback(
        (event) => {
            if (!drawMode || !liveStrokeRef.current) return
            event.preventDefault()

            if (liveStrokeRef.current.kind === 'shape') {
                const point = getNormalizedPointFromEvent(event)
                if (!point) return
                liveStrokeRef.current.end = point
                setDrawings((prev) => {
                    if (prev.length === 0) return [{ ...liveStrokeRef.current }]
                    const draft = prev.slice()
                    draft[draft.length - 1] = { ...liveStrokeRef.current }
                    return draft
                })
                return
            }

            appendDrawingPoint(event)
            setDrawings((prev) => {
                if (prev.length === 0) return [{ ...liveStrokeRef.current }]
                const draft = prev.slice()
                draft[draft.length - 1] = { ...liveStrokeRef.current }
                return draft
            })
        },
        [appendDrawingPoint, drawMode, getNormalizedPointFromEvent]
    )

    const onDrawPointerUp = useCallback(() => {
        const live = liveStrokeRef.current
        if (!live) return

        if (live.kind === 'shape') {
            const width = Math.abs((live.end?.x || 0) - (live.start?.x || 0))
            const height = Math.abs((live.end?.y || 0) - (live.start?.y || 0))
            if (width > 0.003 || height > 0.003) {
                setDrawings((prev) => {
                    const withoutDraft = prev.slice(0, -1)
                    return [...withoutDraft, { ...live }]
                })
            } else {
                setDrawings((prev) => prev.slice(0, -1))
            }
            liveStrokeRef.current = null
            return
        }

        if (Array.isArray(live.points) && live.points.length > 1) {
            setDrawings((prev) => {
                const withoutDraft = prev.slice(0, -1)
                return [...withoutDraft, { ...live }]
            })
        } else {
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
                drawTool={drawTool}
                onToggleDrawMode={() => setDrawMode((prev) => !prev)}
                onSelectDrawTool={(tool) => {
                    setDrawTool(tool)
                    setDrawMode(true)
                }}
                shapeType={shapeType}
                onSelectShape={(shape) => {
                    setShapeType(shape)
                    setDrawTool('shape')
                    setDrawMode(true)
                }}
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
                            <canvas
                                ref={miniDrawingsCanvasRef}
                                width={200}
                                height={128}
                                className="pointer-events-none absolute bottom-3 right-3 z-20 rounded-lg border border-border/70 bg-card/65"
                            />
                        </ReactFlow>
                    )}

                    <canvas
                        ref={drawCanvasRef}
                        className={`absolute inset-0 z-20 ${drawMode ? 'pointer-events-auto' : 'pointer-events-none'} ${drawTool === 'eraser' ? 'cursor-cell' : 'cursor-crosshair'}`}
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
