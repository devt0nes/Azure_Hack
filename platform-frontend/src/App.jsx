import { useEffect, useState } from 'react'
import LandingPage from './pages/LandingPage.jsx'
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
import { getHealth, listProjects, getProjectLogs } from './services/api.js'

const statusToAgentState = {
  created: 'PENDING',
  queued: 'PENDING',
  generating_code: 'RUNNING',
  generating_deployment: 'RUNNING',
  completed: 'COMPLETED',
  failed: 'FAILED',
  paused: 'PENDING',
}

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [agents, setAgents] = useState([])
  const [logs, setLogs] = useState([])
  const [totalTokens, setTotalTokens] = useState(0)
  const [totalCost, setTotalCost] = useState(0)
  const [connectionState, setConnectionState] = useState('disconnected')
  const [activePopup, setActivePopup] = useState(null)
  const [isProfileOpen, setIsProfileOpen] = useState(false)
  const [splitPercent, setSplitPercent] = useState(50)
  const [isResizing, setIsResizing] = useState(false)
  const [hiddenPane, setHiddenPane] = useState('none')
  const [currentProjectId, setCurrentProjectId] = useState('')
  const [currentProjectName, setCurrentProjectName] = useState('No Project Selected')

  const iconClass = (key) =>
    `relative flex h-12 w-12 items-center justify-center rounded-2xl border transition-all duration-300 ${
      activePopup === key
        ? 'border-ember/40 bg-gradient-to-br from-ember/20 to-orange-400/20 text-ember shadow-glow-sm'
        : 'border-white/30 bg-white/50 text-ink/70 hover:border-white/60 hover:bg-white/80 hover:text-ink'
    }`

  const handleLogin = () => {
    setIsLoggedIn(true)
  }

  useEffect(() => {
    if (!isLoggedIn) return

    let isMounted = true

    const updateFromApi = async () => {
      try {
        await getHealth()
        if (isMounted && connectionState !== 'connected') {
          setConnectionState('connected')
        }

        const projectData = await listProjects()
        const projects = Array.isArray(projectData?.projects) ? projectData.projects : []

        if (!isMounted) return

        const mapped = projects.map((project) => ({
          id: project.project_id,
          name: project.project_name || project.project_id,
          state: statusToAgentState[project.status] || 'PENDING',
          progress: project.progress ?? 0,
          tokens_used: 0,
          cost: 0,
        }))

        setAgents(mapped)
        setTotalTokens(0)
        setTotalCost(0)

        if (projects.length > 0) {
          const latestProject = [...projects].sort((a, b) => {
            const aTime = new Date(a.created_at || 0).getTime()
            const bTime = new Date(b.created_at || 0).getTime()
            return bTime - aTime
          })[0]

          setCurrentProjectId(latestProject.project_id)
          setCurrentProjectName(latestProject.project_name || latestProject.project_id)
        } else {
          setCurrentProjectId('')
          setCurrentProjectName('No Project Selected')
        }
      } catch (error) {
        if (isMounted) {
          setConnectionState('disconnected')
          setAgents([])
        }
      }
    }

    updateFromApi()
    const timer = window.setInterval(updateFromApi, 5000)

    return () => {
      isMounted = false
      window.clearInterval(timer)
    }
  }, [isLoggedIn])

  useEffect(() => {
    if (!isLoggedIn || !currentProjectId) {
      setLogs([])
      return
    }

    let isMounted = true

    const updateLogs = async () => {
      try {
        const logData = await getProjectLogs({ projectId: currentProjectId })
        const logMap = logData?.logs || {}
        const flattened = Object.entries(logMap).flatMap(([fileName, content]) => {
          const lines = (content || '')
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean)
            .slice(-20)
            .map((line) => `[${fileName}] ${line}`)

          return lines
        })

        if (isMounted) {
          setLogs(flattened.length > 0 ? flattened.slice(-100) : [])
        }
      } catch (error) {
        if (isMounted) {
          setLogs([])
        }
      }
    }

    updateLogs()
    const timer = window.setInterval(updateLogs, 5000)

    return () => {
      isMounted = false
      window.clearInterval(timer)
    }
  }, [isLoggedIn, currentProjectId])

  useEffect(() => {
    if (!isLoggedIn) return // Don't set up SignalR until logged in
    
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
  }, [isLoggedIn])

  useEffect(() => {
    if (!isResizing) return

    const onMouseMove = (event) => {
      const container = document.getElementById('workspace-split-container')
      if (!container) return

      const rect = container.getBoundingClientRect()
      const next = ((event.clientX - rect.left) / rect.width) * 100
      const clamped = Math.min(80, Math.max(20, next))
      setSplitPercent(clamped)
      if (hiddenPane !== 'none') {
        setHiddenPane('none')
      }
    }

    const onMouseUp = () => setIsResizing(false)

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)

    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [isResizing, hiddenPane])

  // Show landing page if not logged in
  if (!isLoggedIn) {
    return <LandingPage onLogin={handleLogin} />
  }

  const closePopup = () => setActivePopup(null)
  const togglePopup = (key) => setActivePopup((prev) => (prev === key ? null : key))

  const renderPopupContent = () => {
    if (activePopup === 'agents') {
      return (
        <div className="space-y-4">
          {agents.map((agent) => (
            <AgentCard key={agent.id} {...agent} />
          ))}
        </div>
      )
    }

    if (activePopup === 'learning') {
      return <LearningMode projectId={currentProjectId} />
    }

    if (activePopup === 'logs') {
      return <LogStream logs={logs} />
    }

    if (activePopup === 'feedback') {
      return <FeedbackPanel />
    }

    if (activePopup === 'aeg') {
      return <AEGView projectId={currentProjectId} />
    }

    return null
  }

  const popupTitle =
    activePopup === 'agents'
      ? 'Agent Status'
      : activePopup === 'learning'
      ? 'Learning Assistant'
      : activePopup === 'logs'
      ? 'Live Logs'
      : activePopup === 'feedback'
      ? 'Feedback'
      : activePopup === 'aeg'
      ? 'Agent Execution Graph'
      : ''

  return (
    <div className="h-screen overflow-hidden bg-gradient-to-br from-sand via-white to-haze text-midnight">
      <div className="relative overflow-hidden">
        {/* Animated background elements */}
        <div className="absolute inset-0 overflow-hidden">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(242,106,46,0.15),_transparent_60%)]" />
          <div className="absolute -right-32 top-0 h-96 w-96 animate-float rounded-full bg-gradient-to-br from-ember/15 via-orange-400/10 to-transparent blur-3xl" />
          <div className="absolute -left-32 bottom-0 h-96 w-96 animate-float rounded-full bg-gradient-to-tr from-emerald-500/10 via-teal-400/5 to-transparent blur-3xl" style={{ animationDelay: '2s' }} />
          <div className="absolute right-1/3 top-1/3 h-64 w-64 animate-pulse-slow rounded-full bg-gradient-to-r from-amber-300/10 to-transparent blur-2xl" />
        </div>

        <aside className="fixed left-0 top-0 z-30 h-screen w-20 border-r border-white/30 bg-gradient-to-b from-white/85 via-white/70 to-white/55 p-3 backdrop-blur-md shadow-glass">
          <div className="mt-6 flex h-full flex-col items-center gap-3">
            <button
              onClick={() => togglePopup('agents')}
              className={`${iconClass('agents')} group`}
              title="Agent Status"
              aria-label="Open agent status panel"
            >
              {activePopup === 'agents' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-ember" />}
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="8.5" cy="7" r="3" />
                <path d="M20 8v6" />
                <path d="M23 11h-6" />
              </svg>
              <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                Agent Status
              </span>
            </button>
            <button
              onClick={() => togglePopup('learning')}
              className={`${iconClass('learning')} group`}
              title="Learning Agent"
              aria-label="Open learning assistant panel"
            >
              {activePopup === 'learning' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-ember" />}
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M2 8l10-4 10 4-10 4-10-4z" />
                <path d="M6 10v4c0 2.2 2.7 4 6 4s6-1.8 6-4v-4" />
              </svg>
              <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                Learning Assistant
              </span>
            </button>
            <button
              onClick={() => togglePopup('logs')}
              className={`${iconClass('logs')} group`}
              title="Live Logs"
              aria-label="Open live logs panel"
            >
              {activePopup === 'logs' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-ember" />}
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <rect x="4" y="3" width="16" height="18" rx="2" />
                <path d="M8 7h8" />
                <path d="M8 12h8" />
                <path d="M8 17h5" />
              </svg>
              <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                Live Logs
              </span>
            </button>
            <button
              onClick={() => togglePopup('feedback')}
              className={`${iconClass('feedback')} group`}
              title="Feedback"
              aria-label="Open feedback panel"
            >
              {activePopup === 'feedback' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-ember" />}
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M4 21l4-1 10-10-3-3L5 17l-1 4z" />
                <path d="M14 7l3 3" />
              </svg>
              <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                Feedback
              </span>
            </button>
            <button
              onClick={() => togglePopup('aeg')}
              className={`${iconClass('aeg')} group`}
              title="AEG"
              aria-label="Open AEG panel"
            >
              {activePopup === 'aeg' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-ember" />}
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <circle cx="6" cy="6" r="2" />
                <circle cx="18" cy="6" r="2" />
                <circle cx="12" cy="18" r="2" />
                <path d="M8 7l3 9" />
                <path d="M16 7l-3 9" />
                <path d="M8 6h8" />
              </svg>
              <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                Agent Execution Graph
              </span>
            </button>
          </div>
        </aside>

        <div className="relative flex h-screen min-h-0 flex-col py-4 pl-[88px] pr-6 lg:pr-8">
          <header className="relative z-50 animate-fade-in px-4">
            <div className="rounded-3xl border border-white/30 bg-gradient-to-br from-white/80 via-white/65 to-white/50 p-4 shadow-glass backdrop-blur-md">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-[280px] flex-1">
                  <p className="mono text-xs uppercase tracking-[0.35em] bg-gradient-to-r from-ember to-orange-400 bg-clip-text text-transparent font-bold">
                    PLATFORM A
                  </p>
                  <h1 className="mt-1 text-3xl md:text-4xl font-bold bg-gradient-to-r from-midnight via-ink to-midnight bg-clip-text text-transparent leading-tight">
                    Command Center
                  </h1>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink/70">
                    <span className="inline-flex items-center gap-2 rounded-full border border-white/30 bg-white/70 px-2.5 py-1">
                      <span
                        className={`h-2.5 w-2.5 rounded-full shadow-lg transition-all ${
                          connectionState === 'connected'
                            ? 'bg-emerald-500 shadow-green-500/50 animate-glow-pulse'
                            : connectionState === 'reconnecting'
                            ? 'bg-amber-500 shadow-amber-500/50 animate-pulse'
                            : 'bg-red-500/70'
                        }`}
                        title={`SignalR: ${connectionState}`}
                      />
                      Workspace: <span className="mono font-semibold text-ink">{currentProjectName}</span>
                    </span>
                    <span className="inline-flex items-center rounded-full border border-white/30 bg-white/70 px-2.5 py-1">
                      Open Panel: <span className="mono ml-1 max-w-[140px] truncate font-semibold text-ink" title={popupTitle || 'None'}>{popupTitle || 'None'}</span>
                    </span>
                    <span className="inline-flex items-center rounded-full border border-white/30 bg-white/70 px-2.5 py-1">
                      Layout: <span className="mono ml-1 font-semibold text-ink">{hiddenPane === 'none' ? 'Split' : hiddenPane === 'director' ? 'Preview Only' : 'Director Only'}</span>
                    </span>
                  </div>
                </div>

                <div className="animate-slide-in-right relative flex items-start gap-3">
                  <CostTicker tokens={totalTokens} cost={totalCost} />
                  <button
                    onClick={() => setIsProfileOpen((prev) => !prev)}
                    className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/30 bg-white/70 text-ink/80 backdrop-blur-sm transition hover:bg-white/90"
                    title="Account"
                    aria-label="Open account menu"
                  >
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <circle cx="12" cy="8" r="4" />
                      <path d="M4 20a8 8 0 0 1 16 0" />
                    </svg>
                  </button>

                  {isProfileOpen && (
                    <div className="absolute right-0 top-14 z-[120] w-80 rounded-2xl border border-white/30 bg-white/95 p-4 shadow-2xl backdrop-blur-md">
                      <div className="mb-3 flex items-center justify-between">
                        <h3 className="text-sm font-bold text-ink">Account</h3>
                        <button
                          onClick={() => setIsProfileOpen(false)}
                          className="rounded-md bg-ink/5 px-2 py-1 text-xs text-ink/70 hover:bg-ink/10"
                        >
                          Close
                        </button>
                      </div>
                      <div className="space-y-2 text-sm text-ink/70">
                        <p>
                          Active Project: <span className="mono font-semibold text-ink">{currentProjectName}</span>
                        </p>
                        <p>
                          Project ID: <span className="mono font-semibold text-ink">{currentProjectId || 'N/A'}</span>
                        </p>
                        <p>
                          Source: <span className="mono font-semibold text-ink">Backend API</span>
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </header>

          <main className="relative z-10 mt-4 flex-1 min-h-0 pl-4">
            <div className="flex h-full min-h-0 items-stretch gap-4">
              {activePopup && (
                <aside className="w-[430px] rounded-3xl border border-white/30 bg-gradient-to-br from-white/95 via-white/90 to-white/85 shadow-2xl backdrop-blur-lg animate-fade-in flex flex-col">
                  <div className="border-b border-ink/10 p-5">
                    <div className="flex items-center justify-between">
                      <h2 className="text-lg font-bold bg-gradient-to-r from-ink to-ink/70 bg-clip-text text-transparent">{popupTitle}</h2>
                      <button
                        onClick={closePopup}
                        className="rounded-lg bg-ink/5 px-3 py-1.5 text-sm font-medium text-ink/70 transition hover:bg-ink/10 hover:text-ink"
                      >
                        Close
                      </button>
                    </div>
                  </div>
                  <div className="min-h-0 flex-1 overflow-auto p-5">
                    {renderPopupContent()}
                  </div>
                </aside>
              )}

              <section id="workspace-split-container" className="relative flex h-full min-h-0 flex-1">
                <div className="flex w-full items-stretch gap-0">
                {hiddenPane !== 'director' && (
                  <div
                    style={{ width: hiddenPane === 'preview' ? '100%' : `${splitPercent}%` }}
                    className="flex min-w-0 flex-col rounded-l-3xl border border-white/30 bg-white/70 p-6 shadow-glass backdrop-blur-sm min-h-0"
                  >
                  <div className="mb-4 flex items-center gap-3">
                    <div className="h-10 w-1 rounded-full bg-gradient-to-b from-ember to-orange-400" />
                    <h2 className="text-xl font-bold bg-gradient-to-r from-ember via-orange-500 to-ember bg-clip-text text-transparent">
                      Director Agent
                    </h2>
                  </div>
                  <div className="min-h-0 flex-1 animate-fade-in">
                    <Conversation projectId={currentProjectId} onProjectChange={setCurrentProjectId} />
                  </div>
                </div>
                )}

                {hiddenPane === 'none' && (
                  <div
                    className={`relative z-10 flex w-3 cursor-col-resize items-center justify-center bg-transparent ${isResizing ? 'opacity-100' : 'opacity-80 hover:opacity-100'}`}
                    onMouseDown={() => setIsResizing(true)}
                    title="Drag to resize"
                  >
                    <div className="h-full w-[2px] bg-gradient-to-b from-ember/40 via-ember/70 to-ember/40" />
                    <div className="absolute flex -translate-y-1/2 flex-col gap-1 rounded-xl border border-white/30 bg-white/80 p-1 shadow-glass backdrop-blur-sm">
                      <button
                        onClick={() => setHiddenPane('preview')}
                        className="rounded-md px-1.5 py-0.5 text-[10px] text-ink/70 hover:bg-ink/10"
                        title="Show director only"
                      >
                        <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M15 18l-6-6 6-6" />
                        </svg>
                      </button>
                      <button
                        onClick={() => setSplitPercent(50)}
                        className="rounded-md px-1.5 py-0.5 text-[10px] text-ink/70 hover:bg-ink/10"
                        title="Reset split"
                      >
                        <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M20 12a8 8 0 1 1-2.34-5.66" />
                          <path d="M20 4v8h-8" />
                        </svg>
                      </button>
                      <button
                        onClick={() => setHiddenPane('director')}
                        className="rounded-md px-1.5 py-0.5 text-[10px] text-ink/70 hover:bg-ink/10"
                        title="Show preview only"
                      >
                        <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M9 18l6-6-6-6" />
                        </svg>
                      </button>
                    </div>
                  </div>
                )}

                {hiddenPane !== 'preview' && (
                  <div
                    style={{ width: hiddenPane === 'director' ? '100%' : `${100 - splitPercent}%` }}
                    className="flex min-w-0 flex-col rounded-r-3xl border border-white/30 bg-gradient-to-br from-haze/70 via-white/60 to-sand/40 p-6 shadow-glass backdrop-blur-sm min-h-0"
                  >
                  <div className="mb-4 flex items-center gap-3">
                    <div className="h-10 w-1 rounded-full bg-gradient-to-b from-ink/70 to-ink/40" />
                    <h2 className="text-xl font-bold bg-gradient-to-r from-ink to-ink/70 bg-clip-text text-transparent">
                      Preview
                    </h2>
                  </div>
                  <div className="min-h-0 flex-1 animate-fade-in">
                    <Preview />
                  </div>
                </div>
                )}

                {hiddenPane !== 'none' && (
                  <button
                    onClick={() => setHiddenPane('none')}
                    className="absolute left-1/2 top-3 z-20 -translate-x-1/2 rounded-xl border border-white/30 bg-white/85 px-3 py-1 text-xs font-medium text-ink/70 shadow-glass backdrop-blur-sm hover:bg-white"
                  >
                    Restore Split View
                  </button>
                )}
              </div>
              </section>
            </div>
          </main>
        </div>
      </div>
    </div>
  )
}