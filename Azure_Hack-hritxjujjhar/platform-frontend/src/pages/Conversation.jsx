import { useMemo, useState } from 'react'
import { clarify, clarifyWithAnswers } from '../services/api.js'

const initialMessages = [
  {
    id: 'welcome',
    role: 'director',
    content:
      'Welcome to Platform A. Describe the build and I will orchestrate the agents.',
  },
]

export default function Conversation({ projectId, onProjectChange }) {
  const [messages, setMessages] = useState(initialMessages)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState('')
  const [pendingQuestions, setPendingQuestions] = useState([])
  const [answerDrafts, setAnswerDrafts] = useState({})
  const [lastUserIntent, setLastUserIntent] = useState('')
  const [activeProjectId, setActiveProjectId] = useState(projectId || '')

  const sortedMessages = useMemo(() => messages, [messages])

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

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-foreground">Conversation</h2>
        <span className="mono text-xs uppercase tracking-[0.2em] text-foreground/50">
          /clarify
        </span>
      </div>

      <div className="mt-4 max-h-[420px] space-y-4 overflow-y-auto pr-2">
        {sortedMessages.map((message) => (
          <div
            key={message.id}
            className={`flex ${
              message.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
          >
            <div
              className={`max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
                message.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-border bg-card text-foreground'
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
            </div>
          </div>
        ))}
      </div>

      {error ? (
        <p className="mt-3 text-sm text-destructive">{error}</p>
      ) : null}

      {pendingQuestions.length > 0 ? (
        <form onSubmit={handleSubmitAnswers} className="mt-5 space-y-3 rounded-2xl border border-border bg-card/80 p-4">
          <p className="mono text-xs uppercase tracking-[0.22em] text-foreground/60">
            Director clarification questions
          </p>
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
          <button
            type="submit"
            disabled={isSending}
            className="rounded-full border border-border bg-card px-5 py-2 text-sm font-semibold text-foreground transition hover:border-foreground/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSending ? 'Submitting...' : 'Submit answers'}
          </button>
        </form>
      ) : null}

      <form onSubmit={handleSubmit} className="mt-5">
        <label className="mono text-xs uppercase tracking-[0.25em] text-foreground/50">
          Your message
        </label>
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
    </div>
  )
}
