import { useState } from 'react'
import { askTutor } from '../services/tutor.js'
import ReactMarkdown from 'react-markdown'

const QUICK_QUESTIONS = [
  'Explain this build',
  'What is the AEG?',
  'How does cost tracking work?',
  'Show me the conversation flow',
]

export default function LearningMode({ projectId }) {
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'tutor',
      content:
        "👋 **Learning Mode activated!** I'm your AI tutor. Ask me anything about how this system works.",
    },
  ])
  const [input, setInput] = useState('')
  const [isAsking, setIsAsking] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    if (!input.trim() || isAsking) return

    if (!projectId) {
      setMessages((prev) => [
        ...prev,
        {
          id: `tutor-${Date.now()}`,
          role: 'tutor',
          content: 'Select or create a project first so I can fetch project-aware guidance.',
        },
      ])
      return
    }

    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsAsking(true)

    try {
      const response = await askTutor({
        projectId,
        question: userMessage.content,
        context: {
          agents: [],
          logs: [],
        },
      })

      const tutorMessage = {
        id: `tutor-${Date.now()}`,
        role: 'tutor',
        content: response.response || 'No response from tutor.',
      }

      setMessages((prev) => [...prev, tutorMessage])
    } catch (error) {
      console.error('Tutor request failed:', error)
      const errorMessage = {
        id: `tutor-${Date.now()}`,
        role: 'tutor',
        content: '⚠️ Unable to reach the tutor. Check API configuration.',
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsAsking(false)
    }
  }

  function handleQuickQuestion(question) {
    setInput(question)
  }

  return (
    <div className="flex h-full min-h-[500px] flex-col bg-transparent">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div>
          <h2 className="text-xl font-semibold text-foreground">Learning Mode</h2>
          <p className="mono text-xs uppercase tracking-[0.2em] text-foreground/50">
            Overview Level
          </p>
        </div>
        <div className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-400">
          GPT-4o
        </div>
      </div>

      <div className="mt-4 flex-1 space-y-4 overflow-y-auto pr-2">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${
              message.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
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
                  <ReactMarkdown
                    components={{
                      h1: ({ children }) => (
                        <h1 className="mb-2 mt-3 text-base font-semibold">
                          {children}
                        </h1>
                      ),
                      h2: ({ children }) => (
                        <h2 className="mb-2 mt-3 text-sm font-semibold">
                          {children}
                        </h2>
                      ),
                      p: ({ children }) => <p className="my-2">{children}</p>,
                      ul: ({ children }) => (
                        <ul className="my-2 ml-4 list-disc space-y-1">
                          {children}
                        </ul>
                      ),
                      ol: ({ children }) => (
                        <ol className="my-2 ml-4 list-decimal space-y-1">
                          {children}
                        </ol>
                      ),
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{message.content}</p>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 space-y-3 border-t border-border pt-4">
        <div className="flex flex-wrap gap-2">
          {QUICK_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => handleQuickQuestion(q)}
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
              placeholder="Ask about the architecture..."
              className="flex-1 rounded-full border border-border bg-secondary/60 px-4 py-3 text-sm text-foreground outline-none focus:border-primary"
            />
            <button
              type="submit"
              disabled={isAsking}
              className="rounded-full border border-border bg-card px-5 py-3 text-sm font-semibold text-foreground transition hover:border-foreground/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-70"
            >
              {isAsking ? 'Asking...' : 'Ask'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
