import { useMemo, useState } from 'react'
import { clarify } from '../services/api.js'

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

      const directorMessage = {
        id: `director-${Date.now()}`,
        role: 'director',
        content: response.director_reply || 'Director acknowledged.',
      }

      setMessages((prev) => [...prev, directorMessage])
    } catch (err) {
      setError('Unable to reach the Director. Check API connectivity.')
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Conversation</h2>
        <span className="mono text-xs uppercase tracking-[0.2em] text-ink/50">
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
              className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
                message.role === 'user'
                  ? 'bg-ember text-white'
                  : 'bg-white text-ink border border-ink/10'
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
            </div>
          </div>
        ))}
      </div>

      {error ? (
        <p className="mt-3 text-sm text-red-600">{error}</p>
      ) : null}

      <form onSubmit={handleSubmit} className="mt-5">
        <label className="text-xs uppercase tracking-[0.25em] text-ink/50">
          Your message
        </label>
        <div className="mt-2 flex items-center gap-3">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask the Director to clarify the build..."
            className="flex-1 rounded-full border border-ink/15 bg-white/80 px-4 py-3 text-sm outline-none focus:border-ember"
          />
          <button
            type="submit"
            disabled={isSending}
            className="rounded-full bg-midnight px-5 py-3 text-sm font-semibold text-white transition hover:bg-midnight/90 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSending ? 'Sending...' : 'Send'}
          </button>
        </div>
      </form>
    </div>
  )
}
