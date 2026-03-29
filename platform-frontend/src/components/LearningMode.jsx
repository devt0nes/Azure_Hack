import { useState, useRef, useEffect, useCallback } from 'react'
import { askTutor, sessionStart, saveTour } from '../services/tutor.js'
import ReactMarkdown from 'react-markdown'

// ── Depth mode configuration ──────────────────────────────────────────────────

const MODES = [
  { id: 'beginner', label: 'Overview', description: 'Plain-English architecture tour' },
  { id: 'intermediate', label: 'Deep Dive', description: 'Module-by-module walkthrough' },
  { id: 'advanced', label: 'Decision Archaeology', description: 'Trace every design decision' },
]

const QUICK_QUESTIONS = {
  beginner: [
    'Explain the architecture',
    'What does each agent do?',
    'How does the frontend connect to the backend?',
    'Walk me through the data flow',
  ],
  intermediate: [
    'Deep dive into the backend module',
    'Explain the database schema',
    'Walk me through the API routes',
    'Were any bugs auto-patched by the Healer?',
  ],
  advanced: [
    'Why was this tech stack chosen?',
    'Trace back the database decision',
    'What alternatives were considered and rejected?',
    'Reconstruct the agent layer ordering reasoning',
  ],
}

// ── Markdown renderer components ──────────────────────────────────────────────

const MD_COMPONENTS = {
  h1: ({ children }) => <h1 className="mb-2 mt-3 text-base font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-3 text-sm font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 mt-2 text-xs font-semibold">{children}</h3>,
  p: ({ children }) => <p className="my-2">{children}</p>,
  ul: ({ children }) => <ul className="my-2 ml-4 list-disc space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 ml-4 list-decimal space-y-1">{children}</ol>,
  code: ({ inline, children }) =>
    inline ? (
      <code className="rounded bg-secondary px-1 py-0.5 text-xs">{children}</code>
    ) : (
      <pre className="my-2 overflow-x-auto rounded border border-border bg-secondary/60 p-3 text-xs leading-relaxed">
        <code>{children}</code>
      </pre>
    ),
}

// ──────────────────────────────────────────────────────────────────────────────

export default function LearningMode({ projectId }) {
  const [depthLevel, setDepthLevel] = useState('beginner')
  const [messages, setMessages] = useState([])
  const [sessionHistory, setSessionHistory] = useState([])
  const [input, setInput] = useState('')
  const [isAsking, setIsAsking] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [tourSaved, setTourSaved] = useState(false)
  const [tourSaving, setTourSaving] = useState(false)
  const messagesEndRef = useRef(null)

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── Session start ───────────────────────────────────────────────────────────

  const initSession = useCallback(async (mode) => {
    if (!projectId) {
      setMessages([{
        id: 'no-project',
        role: 'tutor',
        content: 'Select or create a project first so I can load the build context.',
      }])
      return
    }

    setIsStarting(true)
    setMessages([])
    setSessionHistory([])
    setTourSaved(false)

    try {
      const result = await sessionStart({ projectId, depthLevel: mode })
      setMessages([{
        id: `greeting-${Date.now()}`,
        role: 'tutor',
        content: result.response || 'Learning Mode ready.',
      }])
    } catch (err) {
      console.error('Session start failed:', err)
      setMessages([{
        id: `err-${Date.now()}`,
        role: 'tutor',
        content: `⚠️ Could not load build context for this project. Check that the backend is running.\n\n_Error: ${err.message}_`,
      }])
    } finally {
      setIsStarting(false)
    }
  }, [projectId])

  // Start session once projectId is known, or on first render if already set
  useEffect(() => {
    if (projectId) {
      initSession(depthLevel)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  // ── Mode switch ─────────────────────────────────────────────────────────────

  function handleModeSwitch(mode) {
    if (mode === depthLevel) return
    setDepthLevel(mode)
    initSession(mode)
  }

  // ── Submit question ─────────────────────────────────────────────────────────

  async function handleSubmit(event) {
    event.preventDefault()
    const question = input.trim()
    if (!question || isAsking) return

    if (!projectId) {
      setMessages((prev) => [...prev, {
        id: `tutor-${Date.now()}`,
        role: 'tutor',
        content: 'Select or create a project first.',
      }])
      return
    }

    const userMsg = { id: `user-${Date.now()}`, role: 'user', content: question }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsAsking(true)

    try {
      const result = await askTutor({
        projectId,
        question,
        depthLevel,
        sessionHistory,
      })

      const tutorContent = result.response || 'No response received.'
      setMessages((prev) => [...prev, {
        id: `tutor-${Date.now()}`,
        role: 'tutor',
        content: tutorContent,
      }])

      // Thread history for next call (cap at 10 turns = 20 messages)
      setSessionHistory((prev) => {
        const next = [
          ...prev,
          { role: 'user', content: question },
          { role: 'assistant', content: tutorContent },
        ]
        return next.slice(-20)
      })
    } catch (err) {
      console.error('Tutor request failed:', err)
      setMessages((prev) => [...prev, {
        id: `err-${Date.now()}`,
        role: 'tutor',
        content: `⚠️ Unable to reach the tutor. Check API configuration.\n\n_Error: ${err.message}_`,
      }])
    } finally {
      setIsAsking(false)
    }
  }

  // ── Save tour ───────────────────────────────────────────────────────────────

  async function handleSaveTour() {
    if (!projectId || tourSaving) return
    const name = window.prompt('Name this tour (will be saved to the Blueprint Library):')
    if (!name?.trim()) return

    setTourSaving(true)
    try {
      await saveTour({
        projectId,
        tourName: name.trim(),
        depthLevel,
        messages: sessionHistory,
      })
      setTourSaved(true)
    } catch (err) {
      console.error('Save tour failed:', err)
      window.alert(`Failed to save tour: ${err.message}`)
    } finally {
      setTourSaving(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const activeMode = MODES.find((m) => m.id === depthLevel)
  const showSaveTour = messages.filter((m) => m.role === 'user').length >= 3

  return (
    <div className="flex h-full min-h-[500px] flex-col bg-transparent">

      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div>
          <h2 className="text-xl font-semibold text-foreground">Learning Mode</h2>
          <p className="mono text-xs uppercase tracking-[0.2em] text-foreground/50">
            {activeMode?.description}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {showSaveTour && (
            <button
              onClick={handleSaveTour}
              disabled={tourSaving || tourSaved}
              className="rounded-full border border-border bg-secondary px-3 py-1 text-xs font-semibold text-foreground/70 transition hover:border-primary/50 hover:bg-primary/10 disabled:opacity-50"
            >
              {tourSaved ? '✓ Tour saved' : tourSaving ? 'Saving…' : 'Save tour'}
            </button>
          )}
          <div className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-400">
            GPT-4o
          </div>
        </div>
      </div>

      {/* Mode selector */}
      <div className="mt-3 flex gap-1">
        {MODES.map((mode) => (
          <button
            key={mode.id}
            onClick={() => handleModeSwitch(mode.id)}
            disabled={isStarting || isAsking}
            className={`flex-1 rounded-lg border px-2 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${
              depthLevel === mode.id
                ? 'border-primary/60 bg-primary/10 text-primary'
                : 'border-border bg-secondary/40 text-foreground/60 hover:border-border/80 hover:bg-secondary/70'
            }`}
          >
            {mode.label}
          </button>
        ))}
      </div>

      {/* Message list */}
      <div className="mt-4 flex-1 space-y-4 overflow-y-auto pr-2">
        {isStarting && (
          <div className="flex justify-start">
            <div className="rounded-2xl border border-border bg-card px-4 py-3 text-sm text-foreground/50">
              Loading build context…
            </div>
          </div>
        )}
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
                message.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-border bg-card text-foreground'
              }`}
            >
              {message.role === 'tutor' ? (
                <div className="prose prose-sm max-w-none prose-headings:font-semibold prose-h1:text-base prose-h2:text-sm prose-h3:text-xs prose-p:my-2 prose-strong:text-primary prose-code:rounded prose-code:bg-secondary prose-code:px-1 prose-code:py-0.5 prose-code:text-xs prose-invert">
                  <ReactMarkdown components={MD_COMPONENTS}>
                    {message.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{message.content}</p>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="mt-4 space-y-3 border-t border-border pt-4">
        <div className="flex flex-wrap gap-2">
          {QUICK_QUESTIONS[depthLevel].map((q) => (
            <button
              key={q}
              onClick={() => setInput(q)}
              className="rounded-full border border-border bg-secondary px-3 py-1 text-xs text-foreground/80 hover:border-primary/50 hover:bg-primary/10"
            >
              {q}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit}>
          <div className="flex items-center gap-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                depthLevel === 'advanced'
                  ? 'Ask "why" about any decision…'
                  : depthLevel === 'intermediate'
                  ? 'Name a module to deep dive…'
                  : 'Ask about the architecture…'
              }
              className="flex-1 rounded-full border border-border bg-secondary/60 px-4 py-3 text-sm text-foreground outline-none focus:border-primary"
            />
            <button
              type="submit"
              disabled={isAsking || isStarting}
              className="rounded-full border border-border bg-card px-5 py-3 text-sm font-semibold text-foreground transition hover:border-foreground/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-70"
            >
              {isAsking ? 'Asking…' : 'Ask'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
