import { useEffect, useMemo, useRef, useState } from 'react'
import {
  askQuestion,
  checkQuestionReadiness,
  clarifyWithAnswers,
  executeFromSpecs,
  ingestProjectContext,
  loadCanvas,
  uploadCanvasFile,
} from '../services/api.js'
import { exportCanvasAsContext } from './IdeaCanvas.jsx'

const initialMessages = [
  {
    id: 'welcome',
    role: 'assistant',
    content:
      `👋 Welcome! I'm your Project Specification Assistant. Let's gather the details needed to build your project.

Tell me about what you'd like to create. You can start with a high-level description, and I'll ask follow-up questions to understand your vision, features, technical requirements, and more.

What are you building today?`,
  },
]

function renderMarkdown(text) {
  if (!text) return ''

  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<!\*)\*([^\*]+)\*(?!\*)/g, '<em>$1</em>')
    .replace(/^[\s]*-\s+/gm, '• ')
}

function normalizeForCompare(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/[•*`#>\-]/g, '')
    .trim()
}

function tokenizeForSimilarity(text) {
  const cleaned = normalizeForCompare(text).replace(/[^a-z0-9\s]/g, ' ')
  return new Set(
    cleaned
      .split(' ')
      .map((token) => token.trim())
      .filter((token) => token.length >= 4)
  )
}

function tokenOverlapRatio(textA, textB) {
  const tokensA = tokenizeForSimilarity(textA)
  const tokensB = tokenizeForSimilarity(textB)

  if (tokensA.size === 0 || tokensB.size === 0) return 0

  let intersection = 0
  for (const token of tokensA) {
    if (tokensB.has(token)) intersection += 1
  }

  return intersection / Math.min(tokensA.size, tokensB.size)
}

export default function Conversation({ projectId, onProjectChange, onOpenIdeaCanvas, onExecuteProject }) {
  const [messages, setMessages] = useState(initialMessages)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState('')
  const [pendingQuestions, setPendingQuestions] = useState([])
  const [answerDrafts, setAnswerDrafts] = useState({})
  const [lastUserIntent, setLastUserIntent] = useState('')
  const [activeProjectId, setActiveProjectId] = useState(projectId || '')
  const [includeCanvasContext, setIncludeCanvasContext] = useState(false)
  const [referenceFiles, setReferenceFiles] = useState([])
  const [specReady, setSpecReady] = useState(false)
  const [specPreview, setSpecPreview] = useState('')
  const [completeness, setCompleteness] = useState(0)
  const [questionCount, setQuestionCount] = useState(0)
  const [isCheckingReadiness, setIsCheckingReadiness] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [nextTopics, setNextTopics] = useState([])
  const [ingestionHint, setIngestionHint] = useState('')

  const messagesContainerRef = useRef(null)
  const messagesEndRef = useRef(null)
  const referenceInputRef = useRef(null)

  const sortedMessages = useMemo(() => messages, [messages])

  useEffect(() => {
    const container = messagesContainerRef.current
    if (!container) return

    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight
    const isNearBottom = distanceFromBottom < 80

    if (isNearBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [sortedMessages, pendingQuestions])

  useEffect(() => {
    if (!activeProjectId) return

    const checkReadiness = async () => {
      setIsCheckingReadiness(true)
      try {
        const response = await checkQuestionReadiness({ projectId: activeProjectId })
        setSpecReady(Boolean(response?.is_ready))
        setCompleteness(Number(response?.completeness || 0))
      } catch {
        // no-op: readiness is best-effort
      } finally {
        setIsCheckingReadiness(false)
      }
    }

    checkReadiness()
    const interval = setInterval(checkReadiness, 5000)
    return () => clearInterval(interval)
  }, [activeProjectId])

  async function handleSubmit(event) {
    event.preventDefault()
    if (!input.trim() || isSending) return

    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setError('')
    setIngestionHint('')
    setIsSending(true)

    try {
      const requestProjectId = activeProjectId || projectId || `project-${Date.now()}`
      let payloadInput = userMessage.content
      let legacyCanvasContext = ''
      let legacyFilesBlock = ''

      const canIngest = Boolean(activeProjectId || projectId)
      const shouldIngest = referenceFiles.length > 0 || includeCanvasContext

      if (canIngest && shouldIngest) {
        try {
          const ingestion = await ingestProjectContext({
            projectId: activeProjectId || projectId,
            referenceFiles,
            includeCanvas: includeCanvasContext,
          })
          const ingestionContext = String(ingestion?.questioning_context_markdown || '').trim()
          if (ingestionContext) {
            payloadInput = `${payloadInput}\n\n${ingestionContext}`
            const fileCount = Array.isArray(ingestion?.file_results) ? ingestion.file_results.length : 0
            const hasCanvas = Boolean(ingestion?.canvas_result)
            const details = [
              fileCount > 0 ? `${fileCount} file${fileCount === 1 ? '' : 's'}` : '',
              hasCanvas ? 'canvas' : '',
            ].filter(Boolean).join(' + ')
            setIngestionHint(details ? `Ingestion context attached (${details})` : 'Ingestion context attached')
          }
        } catch {
          // fallback path below keeps existing behavior if ingestion is unavailable
        }
      }

      if (includeCanvasContext && (activeProjectId || projectId)) {
        const canvasPayload = await loadCanvas({ projectId: activeProjectId || projectId })
        const canvasContext = exportCanvasAsContext(canvasPayload?.canvas_data)
        if (canvasContext) {
          legacyCanvasContext = canvasContext
        }
      }

      if (referenceFiles.length > 0) {
        legacyFilesBlock = [
          'Reference files:',
          ...referenceFiles.map((file) => `- ${file.filename}: ${file.url}`),
        ].join('\n')
      }

      const hasIngestionContext = payloadInput.includes('INGESTION CONTEXT (AUTO-GENERATED):')
      if (!hasIngestionContext) {
        if (legacyCanvasContext) {
          payloadInput = `${payloadInput}\n\n${legacyCanvasContext}`
        }
        if (legacyFilesBlock) {
          payloadInput = `${payloadInput}\n\n${legacyFilesBlock}`
        }
      }

      setLastUserIntent(payloadInput)

      const conversationHistory = messages
        .filter((message) => message.role !== 'agent-thinking')
        .map((message) => ({
          role: message.role === 'user' ? 'user' : 'assistant',
          content: message.content,
        }))

      const response = await askQuestion({
        projectId: requestProjectId,
        userMessage: payloadInput,
        conversationHistory,
        questionCount,
      })

      if (response?.project_id && onProjectChange) {
        onProjectChange(response.project_id)
      }
      if (response?.project_id) {
        setActiveProjectId(response.project_id)
      }

      const assistantText = response?.response || 'Got it, thanks for sharing!'

      if (response?.agent_thinking) {
        const thinking = String(response.agent_thinking || '').trim()
        const normalizedThinking = normalizeForCompare(thinking)
        const normalizedAssistant = normalizeForCompare(assistantText)
        const overlap = tokenOverlapRatio(thinking, assistantText)
        const thinkingIsDuplicate =
          !!normalizedThinking &&
          (normalizedAssistant.includes(normalizedThinking) ||
            normalizedThinking.includes(normalizedAssistant) ||
            overlap >= 0.55)

        if (
          thinking &&
          thinking !== 'Gathering information about project vision and requirements...' &&
          !thinkingIsDuplicate
        ) {
          const thinkingMessage = {
            id: `thinking-${Date.now()}`,
            role: 'agent-thinking',
            content: thinking,
          }
          setMessages((prev) => [...prev, thinkingMessage])
        }
      }

      const assistantMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: assistantText,
      }
      setMessages((prev) => [...prev, assistantMessage])

      if (Array.isArray(response?.next_topics) && response.next_topics.length > 0) {
        setNextTopics(response.next_topics)
        const topicsMessage = {
          id: `topics-${Date.now()}`,
          role: 'assistant',
          content: `📋 **Topic suggestions** for deeper detail:\n- ${response.next_topics.join('\n- ')}`,
        }
        setMessages((prev) => [...prev, topicsMessage])
      }

      if (response?.spec_preview) {
        setSpecPreview(response.spec_preview)
      }

      if (response?.question_count !== undefined) {
        const updatedCount = Number(response.question_count || 0)
        setQuestionCount(updatedCount)
        setCompleteness(Math.max(Number(response?.completeness || 0), Math.min(updatedCount * 10, 100)))
        if (response?.must_execute) {
          setSpecReady(true)
        }
      }

      const questions = Array.isArray(response?.questions) ? response.questions : []
      setPendingQuestions(questions)
      if (questions.length > 0) {
        const nextDrafts = {}
        questions.forEach((_, idx) => {
          nextDrafts[String(idx + 1)] = ''
        })
        setAnswerDrafts(nextDrafts)
      }
    } catch {
      setError('Unable to process your input right now. Please check API connectivity and try again.')
    } finally {
      setIsSending(false)
    }
  }

  async function handleUploadReferenceFile(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    const targetProjectId = activeProjectId || projectId
    if (!targetProjectId) {
      setError('Please send one message first to create/select a project before uploading reference files.')
      return
    }

    try {
      setError('')
      const uploaded = await uploadCanvasFile({ projectId: targetProjectId, file })
      setReferenceFiles((prev) => [
        ...prev,
        {
          filename: uploaded?.filename || file.name,
          url: uploaded?.url || '',
        },
      ])
    } catch {
      setError('Unable to upload reference file right now.')
    }
  }

  async function handleSubmitAnswers(event) {
    event.preventDefault()
    const targetProjectId = projectId || activeProjectId
    if (!targetProjectId || pendingQuestions.length === 0 || isSending) return

    const missing = pendingQuestions.some((_, idx) => {
      const key = String(idx + 1)
      return !String(answerDrafts[key] || '').trim()
    })
    if (missing) {
      setError('Please answer all Director questions before continuing.')
      return
    }

    setError('')
    setIsSending(true)
    try {
      const response = await clarifyWithAnswers({
        projectId: targetProjectId,
        userInput: lastUserIntent,
        answers: answerDrafts,
      })

      const directorMessage = {
        id: `director-answers-${Date.now()}`,
        role: 'director',
        content: response.director_reply || 'Thanks, details recorded.',
      }
      setMessages((prev) => [...prev, directorMessage])
      setPendingQuestions([])
      setAnswerDrafts({})
    } catch {
      setError('Unable to submit clarification answers.')
    } finally {
      setIsSending(false)
    }
  }

  async function handleExecuteFromSpecs() {
    if (!activeProjectId) {
      setError('No project selected.')
      return
    }

    if (onExecuteProject) {
      onExecuteProject()
    }

    setError('')
    setIsExecuting(true)
    try {
      await executeFromSpecs({ projectId: activeProjectId })
      const executionMessage = {
        id: `execution-${Date.now()}`,
        role: 'system',
        content:
          '✨ Starting execution with your specifications. The Director Agent is now taking over to create your project structure and distribute tasks to the implementation agents.',
      }
      setMessages((prev) => [...prev, executionMessage])

      if (onProjectChange) {
        onProjectChange(activeProjectId)
      }
    } catch {
      setError('Failed to start execution. Please try again.')
    } finally {
      setIsExecuting(false)
    }
  }

  const effectiveCompleteness = Math.max(completeness, Math.min(questionCount * 10, 100))

  return (
    <div className="h-full min-h-0 flex flex-col">
      <div className="flex-1 min-h-0 flex flex-col gap-3">
        <div
          ref={messagesContainerRef}
          className="flex-1 min-h-0 overflow-y-auto pr-2"
        >
          <div className="flex min-h-full flex-col gap-4 pb-2">
            {sortedMessages.map((message) => (
              <div key={message.id}>
                {message.role === 'agent-thinking' ? (
                  <div className="flex justify-start">
                    <div className="max-w-[80%] rounded-xl bg-blue-50 border border-blue-200 px-4 py-3 text-sm dark:bg-blue-950 dark:border-blue-800">
                      <p className="font-semibold text-blue-900 dark:text-blue-200 mb-2">💭 My Thinking:</p>
                      <div
                        className="whitespace-pre-wrap break-words text-blue-800 dark:text-blue-100 text-xs"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
                      />
                    </div>
                  </div>
                ) : (
                  <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div
                      className={`max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed ${message.role === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : message.role === 'system'
                          ? 'border border-green-500/30 bg-green-500/10 text-foreground'
                          : 'border border-border bg-card text-foreground'
                        }`}
                    >
                      <div
                        className="whitespace-pre-wrap break-words"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
                      />
                    </div>
                  </div>
                )}
              </div>
            ))}

            {pendingQuestions.length > 0 ? (
              <div className="flex justify-start">
                <form
                  onSubmit={handleSubmitAnswers}
                  className="max-w-[80%] space-y-3 rounded-xl border border-border bg-card p-4"
                >
                  <p className="mono text-xs uppercase tracking-[0.22em] text-foreground/60">
                    Director clarification questions
                  </p>
                  <div className="max-h-64 space-y-3 overflow-y-auto pr-1">
                    {pendingQuestions.map((q, idx) => {
                      const key = String(idx + 1)
                      return (
                        <div key={key} className="space-y-2">
                          <p className="text-sm text-foreground">{idx + 1}. {q}</p>
                          <input
                            value={answerDrafts[key] || ''}
                            onChange={(event) =>
                              setAnswerDrafts((prev) => ({ ...prev, [key]: event.target.value }))
                            }
                            placeholder="Type your answer..."
                            className="w-full rounded-xl border border-border bg-secondary/60 px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                          />
                        </div>
                      )
                    })}
                  </div>
                  <button
                    type="submit"
                    disabled={isSending}
                    className="rounded-full border border-border bg-card px-5 py-2 text-sm font-semibold text-foreground transition hover:border-foreground/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {isSending ? 'Submitting...' : 'Submit answers'}
                  </button>
                </form>
              </div>
            ) : null}

            <div ref={messagesEndRef} />
          </div>
        </div>
        <div className="space-y-3 pt-1">
          {error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : null}

          <form onSubmit={handleSubmit}>
            <div className="rounded-2xl border border-border bg-secondary/45 px-3 py-2">
              <div className="flex items-center gap-2">
                <input
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder={
                    questionCount >= 10
                      ? 'Add any additional details or proceed to execution...'
                      : 'Describe your project or dive into suggested topics...'
                  }
                  className="min-w-0 flex-1 rounded-full border border-border bg-background/95 px-4 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-primary dark:bg-card/65"
                />
                <button
                  type="submit"
                  disabled={isSending}
                  className="relative inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-border bg-card px-4 py-2.5 text-sm font-semibold text-foreground transition hover:border-foreground/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {isSending ? (
                    <>
                      <span className="relative inline-flex h-4 w-4 items-center justify-center">
                        <span className="absolute inset-0 rounded-full border border-primary/35 animate-ping" />
                        <span className="h-4 w-4 rounded-full border-2 border-primary/70 border-t-transparent animate-spin" />
                      </span>
                      <span>Sending...</span>
                    </>
                  ) : (
                    'Send'
                  )}
                </button>
                <button
                  type="button"
                  onClick={handleExecuteFromSpecs}
                  disabled={isExecuting || isSending || !activeProjectId}
                  className="group inline-flex h-10 items-center gap-2 overflow-hidden rounded-full border border-green-500/55 bg-green-500/10 px-3 text-sm font-semibold text-green-700 transition-all duration-300 hover:bg-green-500/20 disabled:cursor-not-allowed disabled:opacity-70"
                  title="Execute and generate project"
                  aria-label="Execute and generate project"
                >
                  <span className="mono whitespace-nowrap">Q {Math.min(questionCount, 10)}/10</span>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4 shrink-0">
                    <path d="M5 12h9" />
                    <path d="M11 6l6 6-6 6" />
                  </svg>
                  <span className="max-w-0 whitespace-nowrap text-sm opacity-0 transition-all duration-300 group-hover:max-w-[360px] group-hover:opacity-100">
                    {isExecuting
                      ? 'Starting execution...'
                      : `Execute & Generate Project${questionCount >= 10 ? '' : ` (${questionCount}/10 questions)`}`}
                  </span>
                </button>
              </div>

              <div className="mt-1.5 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => referenceInputRef.current?.click()}
                    className="group relative inline-flex h-8 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-xs font-medium text-foreground transition hover:border-[#F26A2E]/40 hover:text-[#F26A2E]"
                    title="Upload Files"
                    aria-label="Upload Files"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5">
                      <path d="M12 16V4" />
                      <path d="M8 8l4-4 4 4" />
                      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
                    </svg>
                    <span className="mono uppercase tracking-[0.12em]">Upload Files</span>
                  </button>
                  <input
                    ref={referenceInputRef}
                    type="file"
                    className="hidden"
                    onChange={handleUploadReferenceFile}
                  />
                  <div className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-primary/40 bg-primary/12 px-2.5 py-1.5 shadow-[0_0_18px_rgba(242,106,46,0.2)]">
                    <input
                      type="checkbox"
                      checked={includeCanvasContext}
                      onChange={(event) => setIncludeCanvasContext(event.target.checked)}
                      className="h-3.5 w-3.5 accent-primary"
                      title="Include canvas context"
                      aria-label="Include canvas context"
                    />
                    <button
                      type="button"
                      onClick={() => onOpenIdeaCanvas?.()}
                      className="inline-flex items-center gap-1 text-xs font-bold text-primary transition hover:text-[#F26A2E]"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5">
                        <rect x="3" y="3" width="18" height="18" rx="2" />
                        <path d="M8 8h8" />
                        <path d="M8 12h8" />
                        <path d="M8 16h5" />
                      </svg>
                      <span className="mono uppercase tracking-[0.12em]">Idea Canvas</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
            {referenceFiles.length > 0 ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {referenceFiles.map((file, index) => (
                  <span
                    key={`${file.filename}-${index}`}
                    className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-[11px] text-foreground/70"
                  >
                    {file.filename}
                    <button
                      type="button"
                      onClick={() =>
                        setReferenceFiles((prev) => prev.filter((_, itemIndex) => itemIndex !== index))
                      }
                      className="rounded-full text-foreground/50 transition hover:text-destructive"
                      aria-label={`Remove ${file.filename}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            ) : null}

            {ingestionHint ? (
              <p className="mt-2 text-[11px] text-primary/80">✓ {ingestionHint}</p>
            ) : null}
          </form>

          {nextTopics.length > 0 ? (
            <div className="rounded-lg border border-border bg-card px-4 py-3 text-xs text-foreground/70">
              Suggested next topics: {nextTopics.join(' • ')}
            </div>
          ) : null}

          {specPreview ? (
            <details className="rounded-lg border border-border bg-card px-4 py-3 text-xs text-foreground/70">
              <summary className="cursor-pointer select-none">Specification preview ({effectiveCompleteness}%)</summary>
              <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed">{specPreview}</pre>
            </details>
          ) : null}

          {questionCount >= 10 ? (
            <div className="rounded-lg border border-blue-500/50 bg-blue-500/10 px-4 py-3 text-sm dark:border-blue-600/50 dark:bg-blue-950/20">
              <p className="font-semibold text-blue-900 dark:text-blue-200 mb-1">✓ Questions Target Reached</p>
              <p className="text-blue-800 dark:text-blue-300">
                You've gathered {questionCount} questions. You can continue gathering more details or proceed to execution.
              </p>
            </div>
          ) : null}

        </div>
      </div>
    </div>
  )
}
