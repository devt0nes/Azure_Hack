import { useEffect, useState } from 'react'
import Conversation from './pages/Conversation.jsx'
import AEGView from './pages/AEGView.jsx'
import Preview from './pages/Preview.jsx'
import AgentCard from './components/AgentCard.jsx'
import CostTicker from './components/CostTicker.jsx'
import LogStream from './components/LogStream.jsx'
import FeedbackPanel from './components/FeedbackPanel.jsx'
import LearningMode from './components/LearningMode.jsx'
import { createSignalRConnection } from './services/signalr.js'
import BlueprintExport from './components/BlueprintExport.jsx'

const INITIAL_AGENTS = [
  {
    id: 'director-1',
    name: 'Director',
    state: 'RUNNING',
    progress: 62,
    tokens_used: 850,
    cost: 0.021,
  },
  {
    id: 'frontend-engineer-1',
    name: 'Frontend Agent',
    state: 'PENDING',
    progress: 0,
    tokens_used: 0,
    cost: 0,
  },
  {
    id: 'backend-engineer-1',
    name: 'Backend Agent',
    state: 'COMPLETED',
    progress: 100,
    tokens_used: 1250,
    cost: 0.031,
  },
  {
    id: 'qa-engineer-1',
    name: 'QA Agent',
    state: 'FAILED',
    progress: 40,
    tokens_used: 420,
    cost: 0.011,
  },
]

const INITIAL_LOGS = [
  'Bootstrapped project scaffolding.',
  'Connected to /clarify endpoint.',
  'Waiting on agent orchestration events.',
]

export default function App() {
  const [agents, setAgents] = useState(INITIAL_AGENTS)
  const [logs, setLogs] = useState(INITIAL_LOGS)
  const [totalTokens, setTotalTokens] = useState(2520)
  const [totalCost, setTotalCost] = useState(0.063)
  const [connectionState, setConnectionState] = useState('disconnected')
  const [activeTab, setActiveTab] = useState('conversation')

  useEffect(() => {
    let connection
    
    try {
      connection = createSignalRConnection({
        onAgentStatusUpdate: (data) => {
        setAgents((prev) => {
          const existing = prev.find((a) => a.id === data.agent_id)
          if (existing) {
            return prev.map((a) =>
              a.id === data.agent_id
                ? {
                    ...a,
                    state: data.state,
                    progress: data.progress || a.progress,
                    tokens_used: data.tokens_used || a.tokens_used,
                    cost: data.cost || a.cost,
                  }
                : a
            )
          }
          return [
            ...prev,
            {
              id: data.agent_id,
              name: data.agent_id.replace(/-\d+$/, '').replace(/-/g, ' '),
              state: data.state,
              progress: data.progress || 0,
              tokens_used: data.tokens_used || 0,
              cost: data.cost || 0,
            },
          ]
        })

        if (data.logs && data.logs.length > 0) {
          setLogs((prev) => [...prev, ...data.logs])
        }
      },
      onLogMessage: (data) => {
        setLogs((prev) => [...prev, data.message])
      },
      onCostUpdate: (data) => {
        setTotalTokens(data.tokens)
        setTotalCost(data.cost)
      },
      onReconnecting: () => {
        setConnectionState('reconnecting')
      },
      onReconnected: () => {
        setConnectionState('connected')
        setLogs((prev) => [...prev, 'SignalR reconnected'])
      },
      onClose: () => {
        setConnectionState('disconnected')
      },
    })

      connection.start().then((success) => {
        if (success) {
          setConnectionState('connected')
          setLogs((prev) => [...prev, 'SignalR connected'])
        } else {
          setConnectionState('disconnected')
        }
      })
    } catch (error) {
      console.error('SignalR setup failed:', error)
      setConnectionState('disconnected')
    }

    return () => {
      if (connection) {
        connection.stop()
      }
    }
  }, [])

  return (
    <div className="min-h-screen bg-sand text-midnight">
      <div className="relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(242,106,46,0.18),_transparent_60%)]" />
        <div className="absolute right-0 top-0 h-64 w-64 translate-x-24 -translate-y-20 rounded-full bg-ember/20 blur-3xl" />
        <div className="relative mx-auto max-w-6xl px-6 py-8">
          <header className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="mono text-xs uppercase tracking-[0.35em] text-ember">
                PLATFORM A
              </p>
              <h1 className="text-3xl font-semibold">Command Center</h1>
              <div className="flex items-center gap-3">
                <p className="text-sm text-ink/70">
                  Project: <span className="mono">demo-project</span>
                </p>
                <div
                  className={`h-2 w-2 rounded-full ${
                    connectionState === 'connected'
                      ? 'bg-emerald-500'
                      : connectionState === 'reconnecting'
                      ? 'bg-amber-500 animate-pulse'
                      : 'bg-red-500'
                  }`}
                  title={`SignalR: ${connectionState}`}
                />
              </div>
            </div>
            <CostTicker tokens={totalTokens} cost={totalCost} />
          </header>

          <main className="mt-8 grid gap-6 lg:grid-cols-[1fr_2fr_1fr]">
            <section className="space-y-4">
              <div className="rounded-2xl border border-ink/10 bg-white/70 p-4 shadow-sm">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/60">
                  Agent Status
                </h2>
                <div className="mt-4 space-y-3">
                  {agents.map((agent) => (
                    <AgentCard key={agent.id} {...agent} />
                  ))}
                </div>
              </div>
              <div className="rounded-2xl border border-ink/10 bg-white/70 p-4 shadow-sm">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/60">
                  AEG Preview
                </h2>
                <AEGView projectId="demo-project" />
              </div>
            </section>

            <section className="flex min-h-[600px] flex-col rounded-[28px] border border-ink/10 bg-white/80 p-6 shadow-glow">
              <div className="mb-6 flex gap-3">
                <button
                  onClick={() => setActiveTab('conversation')}
                  className={`mono flex-1 rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] transition ${
                    activeTab === 'conversation'
                      ? 'bg-ember text-white'
                      : 'bg-transparent text-ink/50 hover:text-ink'
                  }`}
                >
                  Director
                </button>
                <button
                  onClick={() => setActiveTab('learning')}
                  className={`mono flex-1 rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] transition ${
                    activeTab === 'learning'
                      ? 'bg-ember text-white'
                      : 'bg-transparent text-ink/50 hover:text-ink'
                  }`}
                >
                  Learning
                </button>
                <button
                  onClick={() => setActiveTab('blueprint')}
                  className={`mono flex-1 rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] transition ${
                    activeTab === 'blueprint'
                      ? 'bg-ember text-white'
                      : 'bg-transparent text-ink/50 hover:text-ink'
                  }`}
                >
                  Blueprint
                </button>
              </div>

              {activeTab === 'conversation' && (
                <div className="flex-1">
                  <Conversation projectId="demo-project" />
                  <div className="mt-6 rounded-2xl border border-dashed border-ink/15 bg-haze/70 p-4">
                    <Preview />
                  </div>
                </div>
              )}

              {activeTab === 'learning' && (
                <div className="flex flex-1 flex-col">
                  <LearningMode projectId="demo-project" />
                </div>
              )}

              {activeTab === 'blueprint' && (
                <div className="flex flex-1 flex-col overflow-y-auto">
                  <BlueprintExport projectId="demo-project" />
                </div>
              )}
            </section>

            <section className="space-y-4">
              <LogStream logs={logs} />
              <FeedbackPanel />
            </section>
          </main>
        </div>
      </div>
    </div>
  )
}