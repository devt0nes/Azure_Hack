import { useEffect, useMemo, useRef, useState } from 'react'
import { clarify, clarifyWithAnswers, askQuestion, checkQuestionReadiness, executeFromSpecs } from '../services/api.js'

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

// Helper function to render markdown text as HTML
function renderMarkdown(text) {
  if (!text) return ''
  
  let html = text
    // Convert **text** to <strong>text</strong>
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Convert *text* to <em>text</em> (but only if not already matched by **)
    .replace(/(?<!\*)\*([^\*]+)\*(?!\*)/g, '<em>$1</em>')
    // Convert markdown lists to HTML (lines starting with - )
    .replace(/^[\s]*-\s+/gm, '• ')
  
  return html
}

export default function Conversation({ projectId, onProjectChange }) {
  const [messages, setMessages] = useState(initialMessages)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState('')
  const [pendingQuestions, setPendingQuestions] = useState([])
  const [answerDrafts, setAnswerDrafts] = useState({})
  const [lastUserIntent, setLastUserIntent] = useState('')
  const [activeProjectId, setActiveProjectId] = useState(projectId || '')
  const [mode, setMode] = useState('questioning') // 'questioning' or 'clarification'
  const [specReady, setSpecReady] = useState(false)
  const [specPreview, setSpecPreview] = useState('')
  const [completeness, setCompleteness] = useState(0)
  const [questionCount, setQuestionCount] = useState(0)
  const [isCheckingReadiness, setIsCheckingReadiness] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [nextTopics, setNextTopics] = useState([])
  const messagesContainerRef = useRef(null)
  const messagesEndRef = useRef(null)

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

  // Check readiness periodically
  useEffect(() => {
    if (!activeProjectId || mode === 'clarification') return

    const checkReadiness = async () => {
      setIsCheckingReadiness(true)
      try {
        const response = await checkQuestionReadiness({ projectId: activeProjectId })
        setSpecReady(response.is_ready)
        setCompleteness(response.completeness)
      } catch (err) {
        console.error('Error checking readiness:', err)
      } finally {
        setIsCheckingReadiness(false)
      }
    }

    checkReadiness()
    const interval = setInterval(checkReadiness, 5000) // Check every 5 seconds
    return () => clearInterval(interval)
  }, [activeProjectId, mode])

  async function handleQuestioningSubmit(event) {
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
    setIsSending(true)

    try {
      const requestProjectId = activeProjectId || `project-${Date.now()}`
      
      const conversationHistory = messages
        .filter(m => m.role !== 'agent-thinking')
        .map(m => ({
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content
        }))

      const response = await askQuestion({
        projectId: requestProjectId,
        userMessage: userMessage.content,
        conversationHistory: conversationHistory,
        question_count: questionCount,
      })

      if (response?.project_id && onProjectChange) {
        onProjectChange(response.project_id)
      }
      if (response?.project_id) {
        setActiveProjectId(response.project_id)
      }

      // Add agent thinking message
      if (response.agent_thinking && response.agent_thinking.trim() !== 'Gathering information about project vision and requirements...') {
        const thinkingMessage = {
          id: `thinking-${Date.now()}`,
          role: 'agent-thinking',
          content: response.agent_thinking,
        }
        setMessages((prev) => [...prev, thinkingMessage])
      }

      const assistantMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.response || 'Got it, thanks for sharing!',
      }

      setMessages((prev) => [...prev, assistantMessage])
      
      // Add topic suggestions if available
      if (response.next_topics && response.next_topics.length > 0) {
        setNextTopics(response.next_topics)
        const topicsMessage = {
          id: `topics-${Date.now()}`,
          role: 'assistant',
          content: `📋 **Topic suggestions** for deeper detail:\n- ${response.next_topics.join('\n- ')}`,
        }
        setMessages((prev) => [...prev, topicsMessage])
      }

      // Update question tracking
      if (response.question_count !== undefined) {
        setQuestionCount(response.question_count)
        setCompleteness(Math.min(response.question_count * 10, 100))
        if (response.must_execute) {
          setSpecReady(true)
        }
      }

    } catch (err) {
      console.error('Error:', err)
      setError('Unable to process your input. Please try again.')
    } finally {
      setIsSending(false)
    }
  }

  async function handleClarificationSubmit(event) {
    event.preventDefault()
    if (!input.trim() || isSending) return

    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setLastUserIntent(userMessage.content)
    setError('')
    setIsSending(true)

    try {
      const requestProjectId = projectId || `project-${Date.now()}`
      const response = await clarify({
        projectId: requestProjectId,
        userInput: userMessage.content,
      })

      if (response?.project_id && onProjectChange) {
        onProjectChange(response.project_id)
      }
      if (response?.project_id) {
        setActiveProjectId(response.project_id)
      }

      const directorMessage = {
        id: `director-${Date.now()}`,
        role: 'director',
        content: response.director_reply || 'Director acknowledged.',
      }

      setMessages((prev) => [...prev, directorMessage])
      const questions = Array.isArray(response?.questions) ? response.questions : []
      setPendingQuestions(questions)
      if (questions.length > 0) {
        const nextDrafts = {}
        questions.forEach((_, idx) => {
          nextDrafts[String(idx + 1)] = ''
        })
        setAnswerDrafts(nextDrafts)
      }
    } catch (err) {
      setError('Unable to reach the Director. Check API connectivity.')
    } finally {
      setIsSending(false)
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
    } catch (err) {
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

    setError('')
    setIsExecuting(true)
    try {
      const response = await executeFromSpecs({ projectId: activeProjectId })
      const executionMessage = {
        id: `execution-${Date.now()}`,
        role: 'system',
        content: '✨ Starting execution with your specifications. The Director Agent is now taking over to create your project structure and distribute tasks to the implementation agents.',
      }
      setMessages((prev) => [...prev, executionMessage])
      
      // Notify parent that project is executing
      if (onProjectChange) {
        onProjectChange(activeProjectId)
      }
    } catch (err) {
      console.error('Error executing from specs:', err)
      setError('Failed to start execution. Please try again.')
    } finally {
      setIsExecuting(false)
    }
  }

  const isQuestioningMode = mode === 'questioning'
  const showExecuteButton = isQuestioningMode && !isExecuting

  return (
    <div className="h-full min-h-0 flex flex-col">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div>
          <h2 className="text-xl font-semibold text-foreground">
            {isQuestioningMode ? 'Specification Builder' : 'Conversation'}
          </h2>
          {isQuestioningMode && (
            <p className="text-xs text-foreground/60 mt-1">
              Questions: {Math.min(questionCount, 10)}/10 • 
              {questionCount >= 10 ? ' ✓ Ready to execute' : ' Gathering specifications'}
            </p>
          )}
        </div>
        <span className="mono text-xs uppercase tracking-[0.2em] text-foreground/50">
          {isQuestioningMode ? '/questions' : '/clarify'}
        </span>
      </div>

      <div
        ref={messagesContainerRef}
        className="mt-4 flex-1 min-h-0 space-y-4 overflow-y-auto pr-2"
      >
        {sortedMessages.map((message) => (
          <div key={message.id}>
            {message.role === 'agent-thinking' ? (
              <div className="flex justify-start">
                <div className="max-w-[80%] rounded-xl bg-blue-50 border border-blue-200 px-4 py-3 text-sm dark:bg-blue-950 dark:border-blue-800">
                  <p className="font-semibold text-blue-900 dark:text-blue-200 mb-2">💭 My Thinking:</p>
                  <div className="whitespace-pre-wrap break-words text-blue-800 dark:text-blue-100 text-xs" dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
                </div>
              </div>
            ) : (
              <div
                className={`flex ${
                  message.role === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                <div
                  className={`max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
                    message.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : message.role === 'system'
                      ? 'border border-green-500/30 bg-green-500/10 text-foreground'
                      : 'border border-border bg-card text-foreground'
                  }`}
                >
                  <div className="whitespace-pre-wrap break-words" dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
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

      {error ? (
        <p className="mt-3 text-sm text-destructive">{error}</p>
      ) : null}

      <div className="mt-5 space-y-3">
        {isQuestioningMode && (
          <form onSubmit={isQuestioningMode ? handleQuestioningSubmit : handleClarificationSubmit} className="">
            <label className="mono text-xs uppercase tracking-[0.25em] text-foreground/50">
              {questionCount >= 10 ? 'Additional context (optional)' : 'Tell me more about your project'}
            </label>
            <div className="mt-2 flex items-center gap-3">
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder={questionCount >= 10 ? "Add any additional details or proceed to execution..." : "Describe your project or dive into suggested topics..."}
                className="flex-1 rounded-full border border-border bg-secondary/60 px-4 py-3 text-sm text-foreground outline-none focus:border-primary"
              />
              <button
                type="submit"
                disabled={isSending}
                className="rounded-full border border-border bg-card px-5 py-3 text-sm font-semibold text-foreground transition hover:border-foreground/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-70"
              >
                {isSending ? 'Sending...' : 'Send'}
              </button>
            </div>
          </form>
        )}
        {!isQuestioningMode && (
          <form onSubmit={handleClarificationSubmit} className="">
            <label className="mono text-xs uppercase tracking-[0.25em] text-foreground/50">Your message</label>
            <div className="mt-2 flex items-center gap-3">
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask the Director to clarify the build..."
                className="flex-1 rounded-full border border-border bg-secondary/60 px-4 py-3 text-sm text-foreground outline-none focus:border-primary"
              />
              <button
                type="submit"
                disabled={isSending}
                className="rounded-full border border-border bg-card px-5 py-3 text-sm font-semibold text-foreground transition hover:border-foreground/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-70"
              >
                {isSending ? 'Sending...' : 'Send'}
              </button>
            </div>
          </form>
        )}
        {isQuestioningMode && questionCount >= 10 && (
          <div className="rounded-lg border border-blue-500/50 bg-blue-500/10 px-4 py-3 text-sm dark:border-blue-600/50 dark:bg-blue-950/20">
            <p className="font-semibold text-blue-900 dark:text-blue-200 mb-1">✓ Questions Target Reached</p>
            <p className="text-blue-800 dark:text-blue-300">You've gathered {questionCount} questions. You can continue gathering more details or proceed to execution.</p>
          </div>
        )}

        {showExecuteButton && (
          <button
            onClick={handleExecuteFromSpecs}
            disabled={isExecuting || isSending}
            className="w-full rounded-full border border-green-500/50 bg-green-500/10 px-5 py-3 text-sm font-semibold text-green-600 transition hover:border-green-500/80 hover:bg-green-500/20 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isExecuting ? 'Starting execution...' : `🚀 Execute & Generate Project${questionCount >= 10 ? '' : ' (' + questionCount + '/10 questions)'}`}
          </button>
        )}
      </div>
    </div>
  )
}