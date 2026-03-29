import { useRef, useState } from 'react'

function ToolbarIcon({ children }) {
    return <span className="inline-flex h-4 w-4 items-center justify-center">{children}</span>
}

export default function CanvasToolbar({
    onAddTextNote,
    onAddStickyNote,
    onUploadImage,
    onUploadFile,
    onAddUrl,
    drawMode,
    drawTool,
    onToggleDrawMode,
    onSelectDrawTool,
    shapeType,
    onSelectShape,
    onClearDrawings,
    onClearCanvas,
}) {
    const [stickyColor, setStickyColor] = useState('yellow')
    const [showUrlInput, setShowUrlInput] = useState(false)
    const [urlDraft, setUrlDraft] = useState('')
    const imageInputRef = useRef(null)
    const fileInputRef = useRef(null)

    const submitUrl = () => {
        const value = urlDraft.trim()
        if (!value) return

        onAddUrl(value)
        setUrlDraft('')
        setShowUrlInput(false)
    }

    return (
        <div className="rounded-2xl border border-white/30 bg-white/80 p-2 backdrop-blur-md shadow-glass dark:border-border dark:bg-card/80">
            <div className="flex flex-wrap items-center gap-2">
                <button
                    onClick={onAddTextNote}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-white/40 bg-white/80 px-3 py-2 text-xs font-medium text-ink transition hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:border-border dark:bg-secondary/60 dark:text-foreground"
                >
                    <ToolbarIcon>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <path d="M4 5h16" /><path d="M4 10h16" /><path d="M4 15h10" /><path d="M4 19h7" />
                        </svg>
                    </ToolbarIcon>
                    Add Text Note
                </button>

                <div className="flex items-center gap-2 rounded-xl border border-white/40 bg-white/80 px-2 py-1.5 dark:border-border dark:bg-secondary/60">
                    <label className="text-[11px] font-medium text-ink dark:text-foreground">Sticky</label>
                    <select
                        value={stickyColor}
                        onChange={(event) => setStickyColor(event.target.value)}
                        className="rounded-md border border-white/40 bg-white px-2 py-1 text-[11px] text-ink outline-none dark:border-border dark:bg-card dark:text-foreground"
                    >
                        <option value="yellow">yellow</option>
                        <option value="pink">pink</option>
                        <option value="blue">blue</option>
                    </select>
                    <button
                        onClick={() => onAddStickyNote(stickyColor)}
                        className="inline-flex items-center gap-1 rounded-md border border-white/40 bg-white px-2 py-1 text-[11px] font-medium text-ink transition hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:border-border dark:bg-card dark:text-foreground"
                    >
                        <ToolbarIcon>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                                <path d="M14 3l7 7-4 1-4 4-1 4-7-7 4-1 4-4z" />
                            </svg>
                        </ToolbarIcon>
                        Add Sticky Note
                    </button>
                </div>

                <button
                    onClick={() => imageInputRef.current?.click()}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-white/40 bg-white/80 px-3 py-2 text-xs font-medium text-ink transition hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:border-border dark:bg-secondary/60 dark:text-foreground"
                >
                    <ToolbarIcon>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <rect x="3" y="4" width="18" height="16" rx="2" />
                            <circle cx="9" cy="10" r="1.5" />
                            <path d="M21 16l-5-5-5 5-2-2-6 6" />
                        </svg>
                    </ToolbarIcon>
                    Upload Image
                </button>
                <input
                    ref={imageInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(event) => {
                        const file = event.target.files?.[0]
                        if (file) {
                            onUploadImage(file)
                        }
                        event.target.value = ''
                    }}
                />

                <button
                    onClick={() => fileInputRef.current?.click()}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-white/40 bg-white/80 px-3 py-2 text-xs font-medium text-ink transition hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:border-border dark:bg-secondary/60 dark:text-foreground"
                >
                    <ToolbarIcon>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
                            <path d="M14 3v5h5" />
                        </svg>
                    </ToolbarIcon>
                    Upload File
                </button>
                <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    onChange={(event) => {
                        const file = event.target.files?.[0]
                        if (file) {
                            onUploadFile(file)
                        }
                        event.target.value = ''
                    }}
                />

                <button
                    onClick={() => setShowUrlInput((prev) => !prev)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-white/40 bg-white/80 px-3 py-2 text-xs font-medium text-ink transition hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:border-border dark:bg-secondary/60 dark:text-foreground"
                >
                    <ToolbarIcon>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <path d="M10 13a5 5 0 0 0 7.07 0l2.12-2.12a5 5 0 1 0-7.07-7.07L10 5" />
                            <path d="M14 11a5 5 0 0 0-7.07 0L4.81 13.12a5 5 0 1 0 7.07 7.07L14 19" />
                        </svg>
                    </ToolbarIcon>
                    Add URL
                </button>

                <button
                    onClick={onToggleDrawMode}
                    className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-medium transition dark:border-border ${drawMode
                        ? 'border-[#F26A2E]/60 bg-[#F26A2E]/12 text-[#F26A2E]'
                        : 'border-white/40 bg-white/80 text-ink hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:bg-secondary/60 dark:text-foreground'
                        }`}
                >
                    <ToolbarIcon>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <path d="M12 20h9" />
                            <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
                        </svg>
                    </ToolbarIcon>
                    {drawMode ? 'Drawing On' : 'Draw'}
                </button>

                <div className="flex items-center gap-2 rounded-xl border border-white/40 bg-white/80 px-2 py-1.5 dark:border-border dark:bg-secondary/60">
                    <button
                        onClick={() => onSelectDrawTool('pen')}
                        title="Pen"
                        aria-label="Pen"
                        className={`inline-flex h-8 w-8 items-center justify-center rounded-md border transition ${drawTool === 'pen'
                            ? 'border-[#F26A2E]/60 bg-[#F26A2E]/12 text-[#F26A2E]'
                            : 'border-white/40 bg-white text-ink hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:border-border dark:bg-card dark:text-foreground'
                            }`}
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <path d="M12 20h9" />
                            <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
                        </svg>
                    </button>

                    <button
                        onClick={() => onSelectDrawTool('eraser')}
                        title="Eraser"
                        aria-label="Eraser"
                        className={`inline-flex h-8 w-8 items-center justify-center rounded-md border transition ${drawTool === 'eraser'
                            ? 'border-[#F26A2E]/60 bg-[#F26A2E]/12 text-[#F26A2E]'
                            : 'border-white/40 bg-white text-ink hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:border-border dark:bg-card dark:text-foreground'
                            }`}
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <path d="M3 16l6-6 8 8-4 4H7z" />
                            <path d="M14 5l5 5" />
                        </svg>
                    </button>

                    <div className="flex items-center gap-1">
                        <span className="text-[11px] font-medium text-ink dark:text-foreground">Shape</span>
                        <select
                            value={shapeType}
                            onChange={(event) => onSelectShape(event.target.value)}
                            className="rounded-md border border-white/40 bg-white px-2 py-1 text-[11px] text-ink outline-none dark:border-border dark:bg-card dark:text-foreground"
                        >
                            <option value="rectangle">Rectangle</option>
                            <option value="roundedRectangle">Rounded Rectangle</option>
                            <option value="square">Square</option>
                            <option value="circle">Circle</option>
                            <option value="ellipse">Ellipse</option>
                            <option value="triangle">Triangle</option>
                            <option value="diamond">Diamond</option>
                            <option value="pentagon">Pentagon</option>
                            <option value="hexagon">Hexagon</option>
                            <option value="octagon">Octagon</option>
                            <option value="line">Line</option>
                            <option value="arrow">Arrow</option>
                            <option value="star">Star</option>
                        </select>
                    </div>
                </div>

                <button
                    onClick={onClearDrawings}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-white/40 bg-white/80 px-3 py-2 text-xs font-medium text-ink transition hover:border-red-300 hover:text-red-600 dark:border-border dark:bg-secondary/60 dark:text-foreground"
                >
                    <ToolbarIcon>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <path d="M3 16l6-6 8 8-4 4H7z" />
                            <path d="M14 5l5 5" />
                        </svg>
                    </ToolbarIcon>
                    Clear Drawings
                </button>

                {showUrlInput && (
                    <div className="flex items-center gap-2 rounded-xl border border-white/40 bg-white/90 px-2 py-1.5 dark:border-border dark:bg-card/90">
                        <input
                            value={urlDraft}
                            onChange={(event) => setUrlDraft(event.target.value)}
                            placeholder="https://example.com"
                            className="w-56 rounded-md border border-white/40 bg-white px-2 py-1 text-xs text-ink outline-none dark:border-border dark:bg-secondary/60 dark:text-foreground"
                        />
                        <button
                            onClick={submitUrl}
                            className="rounded-md border border-white/40 bg-white px-2 py-1 text-[11px] font-medium text-ink transition hover:border-[#F26A2E]/40 hover:text-[#F26A2E] dark:border-border dark:bg-secondary/60 dark:text-foreground"
                        >
                            Add
                        </button>
                    </div>
                )}

                <button
                    onClick={onClearCanvas}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-white/40 bg-white/80 px-3 py-2 text-xs font-medium text-ink transition hover:border-red-300 hover:text-red-600 dark:border-border dark:bg-secondary/60 dark:text-foreground"
                >
                    <ToolbarIcon>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                            <path d="M3 6h18" />
                            <path d="M8 6V4h8v2" />
                            <path d="M19 6l-1 14H6L5 6" />
                        </svg>
                    </ToolbarIcon>
                    Clear Canvas
                </button>
            </div>
        </div>
    )
}