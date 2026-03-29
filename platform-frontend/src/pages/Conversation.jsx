import { useEffect, useMemo, useRef, useState } from 'react'
import {
  askQuestion,
  checkQuestionReadiness,
  clarifyWithAnswers,
  createProject,
  executeFromSpecs,
  getProjectApiKeyStatus,
  getProjectLedger,
  ingestProjectContext,
  loadCanvas,
  uploadCanvasFile,
} from '../services/api.js'
import { exportCanvasAsContext } from './IdeaCanvas.jsx'

const CONVERSATION_STATE_PREFIX = 'nexus-conversation-state-v1:'

function getConversationStateStorageKey(projectId) {
  return `${CONVERSATION_STATE_PREFIX}${projectId}`
}

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
  const [requiredApiKeyServices, setRequiredApiKeyServices] = useState([])
  const [serviceApiKeys, setServiceApiKeys] = useState({})
  const [savedApiKeyServices, setSavedApiKeyServices] = useState([])
  const [isApiKeyModalOpen, setIsApiKeyModalOpen] = useState(false)

  const messagesContainerRef = useRef(null)
  const messagesEndRef = useRef(null)
  const referenceInputRef = useRef(null)
  const previousProjectIdRef = useRef(activeProjectId)

  const pushApiKeyInlineNotice = (services) => {
    const cleanServices = (services || [])
      .map((service) => String(service || '').trim())
      .filter(Boolean)

    if (cleanServices.length === 0) return

    setMessages((prev) => {
      const hasExistingNotice = prev.some(
        (msg) =>
          msg?.id?.startsWith('api-key-inline-notice-') ||
          String(msg?.content || '').includes('API keys required before execution')
      )

      if (hasExistingNotice) return prev

      return [
        ...prev,
        {
          id: `api-key-inline-notice-${Date.now()}`,
          role: 'system',
          content: `🔐 API keys required before execution for: ${cleanServices.join(', ')}.\nClick the API Keys button to open the popup and continue execution.`,
        },
      ]
    })
  }

  async function ensureProjectExists(seedIntent = 'Project setup') {
    const existingProjectId = activeProjectId || projectId
    if (existingProjectId) return existingProjectId

    const now = new Date()
    const fallbackName = `Project ${now.toLocaleDateString()} ${now.toLocaleTimeString()}`
    const created = await createProject({
      projectName: fallbackName,
      userIntent: String(seedIntent || 'Project setup').slice(0, 500),
      description: 'Created automatically for pre-prompt assets/canvas context.',
    })

    const createdProjectId = created?.project_id || ''
    if (!createdProjectId) {
      throw new Error('Unable to create project')
    }

    setActiveProjectId(createdProjectId)
    if (onProjectChange) {
      onProjectChange(createdProjectId)
    }

    return createdProjectId
  }

  const sortedMessages = useMemo(() => messages, [messages])

  useEffect(() => {
    if (!projectId) return
    if (projectId !== activeProjectId) {
      setActiveProjectId(projectId)
    }
  }, [projectId, activeProjectId])

  useEffect(() => {
    const previousProjectId = previousProjectIdRef.current
    previousProjectIdRef.current = activeProjectId

    // Reset conversation state only when switching between existing projects.
    // Do not reset on initial project assignment after first user message.
    if (!previousProjectId || !activeProjectId || previousProjectId === activeProjectId) return

    setMessages(initialMessages)
    setInput('')
    setError('')
    setLastUserIntent('')
    setReferenceFiles([])
    setIncludeCanvasContext(false)
    setIngestionHint('')
    setQuestionCount(0)
    setCompleteness(0)
    setSpecReady(false)
    setSpecPreview('')
    setNextTopics([])
    setPendingQuestions([])
    setAnswerDrafts({})
    setRequiredApiKeyServices([])
    setServiceApiKeys({})
    setSavedApiKeyServices([])
    setIsApiKeyModalOpen(false)
  }, [activeProjectId])

  useEffect(() => {
    if (!activeProjectId) return

    try {
      const raw = window.localStorage.getItem(getConversationStateStorageKey(activeProjectId))
      if (!raw) return
      const saved = JSON.parse(raw)

      if (Array.isArray(saved?.messages) && saved.messages.length > 0) {
        setMessages(saved.messages)
      }
      if (typeof saved?.input === 'string') setInput(saved.input)
      if (typeof saved?.lastUserIntent === 'string') setLastUserIntent(saved.lastUserIntent)
      if (typeof saved?.specReady === 'boolean') setSpecReady(saved.specReady)
      if (typeof saved?.specPreview === 'string') setSpecPreview(saved.specPreview)
      if (typeof saved?.completeness === 'number') setCompleteness(saved.completeness)
      if (typeof saved?.questionCount === 'number') setQuestionCount(saved.questionCount)
      if (Array.isArray(saved?.nextTopics)) setNextTopics(saved.nextTopics)
      if (Array.isArray(saved?.pendingQuestions)) setPendingQuestions(saved.pendingQuestions)
      if (saved?.answerDrafts && typeof saved.answerDrafts === 'object') setAnswerDrafts(saved.answerDrafts)
      if (Array.isArray(saved?.requiredApiKeyServices)) setRequiredApiKeyServices(saved.requiredApiKeyServices)
      if (Array.isArray(saved?.savedApiKeyServices)) setSavedApiKeyServices(saved.savedApiKeyServices)
    } catch {
      // no-op: persistence is best effort
    }
  }, [activeProjectId])

  useEffect(() => {
    if (!activeProjectId) return

    const payload = {
      messages,
      input,
      lastUserIntent,
      specReady,
      specPreview,
      completeness,
      questionCount,
      nextTopics,
      pendingQuestions,
      answerDrafts,
      requiredApiKeyServices,
      savedApiKeyServices,
    }

    try {
      window.localStorage.setItem(
        getConversationStateStorageKey(activeProjectId),
        JSON.stringify(payload)
      )
    } catch {
      // no-op: persistence is best effort
    }
  }, [
    activeProjectId,
    messages,
    input,
    lastUserIntent,
    specReady,
    specPreview,
    completeness,
    questionCount,
    nextTopics,
    pendingQuestions,
    answerDrafts,
    requiredApiKeyServices,
    savedApiKeyServices,
  ])

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
        const isReady = Boolean(response?.is_ready)
        setSpecReady(isReady)
        setCompleteness(Number(response?.completeness || 0))

        const readinessServices = Array.isArray(response?.required_api_key_services)
          ? response.required_api_key_services.map((service) => String(service || '').trim()).filter(Boolean)
          : []

        if (isReady) {
          setRequiredApiKeyServices(readinessServices)
          setServiceApiKeys((prev) => {
            const next = { ...prev }
            readinessServices.forEach((service) => {
              if (!(service in next)) next[service] = ''
            })
            return next
          })
          pushApiKeyInlineNotice(readinessServices)
        } else {
          setRequiredApiKeyServices([])
          setServiceApiKeys({})
        }

        if (isReady) {
          const ledgerResponse = await getProjectLedger({ projectId: activeProjectId })
          const ledger = ledgerResponse?.ledger_data || {}
          const services = Array.isArray(ledger?.required_api_key_services)
            ? ledger.required_api_key_services
            : []
          const cleanServices = services
            .map((service) => String(service || '').trim())
            .filter(Boolean)
          if (cleanServices.length > 0) {
            setRequiredApiKeyServices(cleanServices)
            setServiceApiKeys((prev) => {
              const next = { ...prev }
              cleanServices.forEach((service) => {
                if (!(service in next)) next[service] = ''
              })
              return next
            })
            pushApiKeyInlineNotice(cleanServices)
          }

          try {
            const keyStatus = await getProjectApiKeyStatus({ projectId: activeProjectId })
            const savedServices = Array.isArray(keyStatus?.saved_services)
              ? keyStatus.saved_services.map((service) => String(service || '').trim()).filter(Boolean)
              : []
            setSavedApiKeyServices(savedServices)
            if (savedServices.length > 0) {
              setServiceApiKeys((prev) => {
                const next = { ...prev }
                savedServices.forEach((service) => {
                  if (!(service in next)) next[service] = ''
                })
                return next
              })
            }
          } catch {
            setSavedApiKeyServices([])
          }
        } else {
          setSavedApiKeyServices([])
        }
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
      const shouldIngest = referenceFiles.length > 0 || includeCanvasContext
      const requestProjectId = shouldIngest
        ? await ensureProjectExists(userMessage.content)
        : (activeProjectId || projectId || `project-${Date.now()}`)
      let payloadInput = userMessage.content
      let legacyCanvasContext = ''
      let legacyFilesBlock = ''

      const canIngest = Boolean(requestProjectId)

      if (canIngest && shouldIngest) {
        try {
          const ingestion = await ingestProjectContext({
            projectId: requestProjectId,
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

      if (includeCanvasContext && requestProjectId) {
        const canvasPayload = await loadCanvas({ projectId: requestProjectId })
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

    try {
      setError('')
      const targetProjectId = await ensureProjectExists(`Upload reference file: ${file.name}`)
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

    if (!specReady) {
      setError('Specifications are not ready yet. Please answer more questions first.')
      return
    }

    setError('')
    setIsExecuting(true)
    try {
      const ledgerMessage = {
        id: `ledger-gen-${Date.now()}`,
        role: 'system',
        content: '🧠 Director is generating your task ledger from the gathered specifications...',
      }
      setMessages((prev) => [...prev, ledgerMessage])

      const nonEmptyApiKeys = Object.fromEntries(
        Object.entries(serviceApiKeys).filter(([, value]) => String(value || '').trim())
      )

      const response = await executeFromSpecs({ projectId: activeProjectId, serviceApiKeys: nonEmptyApiKeys })
      if (response?.status && response.status !== 'running') {
        const backendMessage = response?.message || 'Execution did not start.'
        const missingServices = Array.isArray(response?.missing_services)
          ? response.missing_services
          : []
        const requiredServices = Array.isArray(response?.required_api_key_services)
          ? response.required_api_key_services
          : []

        const nextRequired = (requiredServices.length > 0 ? requiredServices : missingServices)
          .map((service) => String(service || '').trim())
          .filter(Boolean)

        if (nextRequired.length > 0) {
          setRequiredApiKeyServices(nextRequired)
          setServiceApiKeys((prev) => {
            const next = { ...prev }
            nextRequired.forEach((service) => {
              if (!(service in next)) next[service] = ''
            })
            return next
          })
          setSpecReady(true)
          setIsApiKeyModalOpen(true)
          setMessages((prev) => [
            ...prev,
            {
              id: `api-key-gate-${Date.now()}`,
              role: 'system',
              content: `🔐 Task ledger generated. API keys required for: ${nextRequired.join(', ')}. Please fill the popup to continue.`,
            },
          ])
          setError('Please provide the required API keys to continue execution.')
        }

        if (missingServices.length > 0) {
          setError(`${backendMessage} Missing: ${missingServices.join(', ')}`)
        } else {
          setError(backendMessage)
        }
        setIsExecuting(false)
        return
      }

      const executionMessage = {
        id: `execution-${Date.now()}`,
        role: 'system',
        content:
          '✨ Task ledger is ready. Starting agent execution and opening AEG + Preview.',
      }
      setMessages((prev) => [...prev, executionMessage])
      setIsApiKeyModalOpen(false)

      if (onExecuteProject && response?.orchestration_started !== false) {
        onExecuteProject()
      }

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
  const hasApiKeyRequirements = requiredApiKeyServices.length > 0

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
                  disabled={isExecuting || isSending || !activeProjectId || !specReady}
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
                  {hasApiKeyRequirements ? (
                    <button
                      type="button"
                      onClick={() => setIsApiKeyModalOpen(true)}
                      className="inline-flex h-8 items-center rounded-full border border-amber-500/55 bg-amber-500/10 px-3 text-xs font-semibold text-amber-700 transition hover:bg-amber-500/20"
                      title="Open API key popup"
                      aria-label="Open API key popup"
                    >
                      API Keys
                    </button>
                  ) : null}
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

      {isApiKeyModalOpen && requiredApiKeyServices.length > 0 ? (
        <div className="fixed inset-0 z-[180] flex items-center justify-center bg-black/45 px-4">
          <div className="w-full max-w-xl rounded-2xl border border-amber-500/45 bg-card p-5 shadow-2xl">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h3 className="text-base font-bold text-foreground">API keys required to continue</h3>
                <p className="mt-1 text-xs text-foreground/70">
                  We generated your task ledger. Please provide keys for required services, then continue execution.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsApiKeyModalOpen(false)}
                className="rounded-lg border border-border bg-card px-2 py-1 text-xs font-semibold text-foreground/70 transition hover:bg-accent"
              >
                Close
              </button>
            </div>

            <div className="space-y-3">
              {requiredApiKeyServices.map((service) => (
                <div key={service} className="space-y-1">
                  <label className="text-xs font-medium text-amber-800">
                    {service} API Key
                    {savedApiKeyServices.includes(service) ? (
                      <span className="ml-2 text-[11px] font-semibold text-emerald-700">Saved on backend</span>
                    ) : null}
                  </label>
                  <input
                    type="password"
                    value={serviceApiKeys[service] || ''}
                    onChange={(event) =>
                      setServiceApiKeys((prev) => ({
                        ...prev,
                        [service]: event.target.value,
                      }))
                    }
                    placeholder={`Enter ${service} API key`}
                    className="w-full rounded-xl border border-amber-300/60 bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-amber-500"
                  />
                </div>
              ))}
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsApiKeyModalOpen(false)}
                className="rounded-full border border-border bg-card px-4 py-2 text-xs font-semibold text-foreground transition hover:bg-accent"
              >
                Save for later
              </button>
              <button
                type="button"
                onClick={handleExecuteFromSpecs}
                disabled={isExecuting || isSending}
                className="rounded-full border border-green-500/55 bg-green-500/12 px-4 py-2 text-xs font-semibold text-green-700 transition hover:bg-green-500/20 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {isExecuting ? 'Submitting...' : 'Submit keys & continue'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}