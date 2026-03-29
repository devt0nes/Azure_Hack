import { useEffect, useRef, useState } from 'react'
import { auth } from './firebaseConfig'
import { logout } from './firebaseConfig'
import LandingPage from './pages/LandingPage.jsx'
import Conversation from './pages/Conversation.jsx'
import AEGView from './pages/AEGView.jsx'
import IdeaCanvas from './pages/IdeaCanvas.jsx'
import Preview from './pages/Preview.jsx'
import AgentMarketplace from './pages/AgentMarketplace.jsx'
import AgentCard from './components/AgentCard.jsx'
import CostTicker from './components/CostTicker.jsx'
import LogStream from './components/LogStream.jsx'
import FeedbackPanel from './components/FeedbackPanel.jsx'
import LearningMode from './components/LearningMode.jsx'
import CostOptimizerPanel from './components/CostOptimizerPanel.jsx'
import AnimatedGridBackground from './components/AnimatedGridBackground.jsx'
import { createSignalRConnection } from './services/signalr.js'
import { getHealth, listProjects, getProjectLogs, getProject } from './services/api.js'

const THEME_STORAGE_KEY = 'platform-theme'

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
  const [user, setUser] = useState(null)           // ← was: isLoggedIn boolean
  const [authLoading, setAuthLoading] = useState(true) // ← prevent flash of login screen
  const [agents, setAgents] = useState([])
  const [logs, setLogs] = useState([])
  const [totalTokens, setTotalTokens] = useState(0)
  const [totalCost, setTotalCost] = useState(0)
  const [connectionState, setConnectionState] = useState('disconnected')
  const [activePopup, setActivePopup] = useState(null)
  const [isProfileOpen, setIsProfileOpen] = useState(false)
  const [splitPercent, setSplitPercent] = useState(50)
  const [isResizing, setIsResizing] = useState(false)
  const [hiddenPane, setHiddenPane] = useState('preview')
  const [currentProjectId, setCurrentProjectId] = useState('')
  const [currentProjectName, setCurrentProjectName] = useState('No Project Selected')
  const [currentProjectData, setCurrentProjectData] = useState(null)
  const [theme, setTheme] = useState('light')
  const [showMarketplace, setShowMarketplace] = useState(false)
  const [showIdeaCanvas, setShowIdeaCanvas] = useState(false)
  const [canvasSaveState, setCanvasSaveState] = useState('saved')
  const [selectedAegNodeId, setSelectedAegNodeId] = useState(null)
  const [isSidebarExpanded, setIsSidebarExpanded] = useState(false)
  const [isProjectMenuOpen, setIsProjectMenuOpen] = useState(false)
  const [isProjectSwitching, setIsProjectSwitching] = useState(false)
  const [projectSwitchNotice, setProjectSwitchNotice] = useState(null)
  const projectMenuRef = useRef(null)
  const projectSwitchPulseTimerRef = useRef(null)
  const projectSwitchNoticeTimerRef = useRef(null)

  useEffect(() => {
    const saved = typeof window !== 'undefined' ? window.localStorage.getItem(THEME_STORAGE_KEY) : null
    if (saved === 'dark' || saved === 'light') {
      setTheme(saved)
    }
  }, [])

  useEffect(() => {
    if (typeof document === 'undefined') return
    document.documentElement.classList.toggle('dark', theme === 'dark')
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [theme])

  const toggleTheme = () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))

  // Start from the landing page on each fresh app load.
  // This clears any previously persisted Firebase session so localhost
  // doesn't jump straight into the command center.
  useEffect(() => {
    let unsubscribe = () => { }
    let cancelled = false

    const initAuth = async () => {
      try {
        await logout()
      } catch {
        // Ignore startup logout errors; we still want auth state to resolve.
      }

      if (cancelled) return

      unsubscribe = auth.onAuthStateChanged((firebaseUser) => {
        setUser(firebaseUser ?? null)
        setAuthLoading(false)
      })
    }

    initAuth()

    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [])

  const handleLogin = (firebaseUser) => {
    setUser(firebaseUser)
  }

  const handleLogout = async () => {
    await logout()
    setUser(null)
    setIsProfileOpen(false)
    setAgents([])
    setLogs([])
    setCurrentProjectId('')
    setCurrentProjectName('No Project Selected')
    setCurrentProjectData(null)
    setShowMarketplace(false)
    setShowIdeaCanvas(false)
    setActivePopup(null)
  }

  const handleExecuteProject = () => {
    setShowMarketplace(false)
    setShowIdeaCanvas(false)
    setHiddenPane('director')
    setActivePopup('aeg')
  }

  const isLoggedIn = !!user  // ← rest of the component uses this unchanged

  const iconClass = (key) =>
    `relative flex h-10 ${isSidebarExpanded ? 'w-[96%] self-center gap-2.5 px-2.5 pr-3.5 overflow-visible' : 'w-10 px-2.5 overflow-hidden'} justify-start items-center rounded-xl border origin-left transition-all duration-300 ${activePopup === key
      ? 'border-primary/60 bg-gradient-to-r from-primary/30 to-primary/10 text-primary shadow-glow-sm'
      : 'border-border/55 bg-gradient-to-r from-card/90 via-card/60 to-primary/[0.08] text-foreground/80 backdrop-blur-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_10px_20px_-16px_rgba(0,0,0,0.55)] hover:border-primary/35 hover:from-card/95 hover:via-card/70 hover:to-primary/[0.14] hover:text-foreground'
    }`

  const sidebarLabelClass = `text-[13px] font-medium whitespace-nowrap overflow-hidden origin-left transition-all duration-300 ${isSidebarExpanded
    ? 'max-w-[182px] opacity-100 translate-x-0'
    : 'max-w-0 opacity-0 -translate-x-1'
    }`

  const getAgentStateClasses = (state) => {
    if (state === 'RUNNING') return 'border-amber-500/35 bg-amber-500/12 text-amber-300'
    if (state === 'COMPLETED') return 'border-emerald-500/35 bg-emerald-500/12 text-emerald-300'
    if (state === 'FAILED') return 'border-red-500/35 bg-red-500/12 text-red-300'
    return 'border-primary/30 bg-primary/10 text-primary'
  }

  const clearProjectSwitchTimers = () => {
    if (projectSwitchPulseTimerRef.current) {
      window.clearTimeout(projectSwitchPulseTimerRef.current)
      projectSwitchPulseTimerRef.current = null
    }
    if (projectSwitchNoticeTimerRef.current) {
      window.clearTimeout(projectSwitchNoticeTimerRef.current)
      projectSwitchNoticeTimerRef.current = null
    }
  }

  const switchProject = (nextProjectId, source = 'manual') => {
    if (!nextProjectId) {
      setCurrentProjectId('')
      setCurrentProjectName('No Project Selected')
      setIsProjectMenuOpen(false)
      return
    }

    if (nextProjectId === currentProjectId) {
      setIsProjectMenuOpen(false)
      return
    }

    const targetProject = agents.find((agent) => agent.id === nextProjectId)
    const targetName = targetProject?.name || nextProjectId
    const targetState = targetProject?.state || 'PENDING'
    const targetProgress = Math.max(0, Math.min(100, Math.round(targetProject?.progress ?? 0)))

    clearProjectSwitchTimers()
    setCurrentProjectId(nextProjectId)
    setCurrentProjectName(targetName)
    setIsProjectMenuOpen(false)
    setIsProjectSwitching(true)
    setProjectSwitchNotice({
      id: nextProjectId,
      name: targetName,
      state: targetState,
      progress: targetProgress,
      source,
    })

    projectSwitchPulseTimerRef.current = window.setTimeout(() => {
      setIsProjectSwitching(false)
      projectSwitchPulseTimerRef.current = null
    }, 1400)

    projectSwitchNoticeTimerRef.current = window.setTimeout(() => {
      setProjectSwitchNotice(null)
      projectSwitchNoticeTimerRef.current = null
    }, 2800)
  }

  const activeProject = agents.find((agent) => agent.id === currentProjectId) || null
  const activeProjectState = activeProject?.state || 'PENDING'
  const activeProjectProgress = Math.max(0, Math.min(100, Math.round(activeProject?.progress ?? 0)))

  useEffect(() => {
    return () => clearProjectSwitchTimers()
  }, [])

  useEffect(() => {
    if (!isProjectMenuOpen) return

    const handlePointerDown = (event) => {
      if (projectMenuRef.current && !projectMenuRef.current.contains(event.target)) {
        setIsProjectMenuOpen(false)
      }
    }

    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        setIsProjectMenuOpen(false)
      }
    }

    window.addEventListener('mousedown', handlePointerDown)
    window.addEventListener('keydown', handleEscape)

    return () => {
      window.removeEventListener('mousedown', handlePointerDown)
      window.removeEventListener('keydown', handleEscape)
    }
  }, [isProjectMenuOpen])

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

        if (projects.length === 0) {
          setCurrentProjectId('')
          setCurrentProjectName('No Project Selected')
          return
        }

        if (currentProjectId) {
          const selectedProject = projects.find((project) => project.project_id === currentProjectId)
          if (selectedProject) {
            setCurrentProjectName(selectedProject.project_name || selectedProject.project_id)
          } else {
            setCurrentProjectId('')
            setCurrentProjectName('No Project Selected')
          }
        } else {
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
  }, [isLoggedIn, currentProjectId])

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
        if (isMounted) setLogs([])
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
    if (!isLoggedIn || !currentProjectId) {
      setCurrentProjectData(null)
      return
    }

    let isMounted = true

    const fetchProjectData = async () => {
      try {
        const data = await getProject({ projectId: currentProjectId })
        if (isMounted) setCurrentProjectData(data)
      } catch (error) {
        if (isMounted) setCurrentProjectData(null)
      }
    }

    fetchProjectData()
    const timer = window.setInterval(fetchProjectData, 5000)

    return () => {
      isMounted = false
      window.clearInterval(timer)
    }
  }, [isLoggedIn, currentProjectId])

  useEffect(() => {
    if (!isLoggedIn) return

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
        onReconnecting: () => setConnectionState('reconnecting'),
        onReconnected: () => {
          setConnectionState('connected')
          setLogs((prev) => [...prev, 'SignalR reconnected'])
        },
        onClose: () => setConnectionState('disconnected'),
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
      if (connection) connection.stop()
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
      if (hiddenPane !== 'none') setHiddenPane('none')
    }

    const onMouseUp = () => setIsResizing(false)

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)

    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [isResizing, hiddenPane])

  // ← Show nothing while Firebase restores session (prevents flash)
  if (authLoading) return null

  if (!isLoggedIn) {
    return <LandingPage onLogin={handleLogin} theme={theme} onToggleTheme={toggleTheme} />
  }

  const closePopup = () => setActivePopup(null)
  const togglePopup = (key) => {
    setShowMarketplace(false)
    setShowIdeaCanvas(false)
    setActivePopup((prev) => (prev === key ? null : key))
  }

  const openMarketplace = () => {
    setActivePopup(null)
    setShowIdeaCanvas(false)
    setShowMarketplace(true)
  }

  const openIdeaCanvas = () => {
    setActivePopup(null)
    setShowMarketplace(false)
    setCanvasSaveState('saved')
    setShowIdeaCanvas(true)
  }

  const canvasSaveLabel =
    canvasSaveState === 'saving' ? 'Saving…' :
      canvasSaveState === 'unsaved' ? 'Unsaved changes' :
        canvasSaveState === 'saved-local' ? 'Saved locally' :
          canvasSaveState === 'error' ? 'Save failed' : 'Saved'

  const canvasSaveClasses =
    canvasSaveState === 'saving' ? 'border-amber-500/35 bg-amber-500/12 text-amber-300' :
      canvasSaveState === 'unsaved' ? 'border-orange-500/35 bg-orange-500/12 text-orange-300' :
        canvasSaveState === 'saved-local' ? 'border-sky-500/35 bg-sky-500/12 text-sky-300' :
          canvasSaveState === 'error' ? 'border-red-500/40 bg-red-500/12 text-red-300' :
            'border-emerald-500/35 bg-emerald-500/12 text-emerald-300'

  const togglePreviewPane = () => {
    setHiddenPane((prev) => (prev === 'preview' ? 'none' : 'preview'))
  }

  const toggleDirectorPane = () => {
    setHiddenPane((prev) => (prev === 'director' ? 'none' : 'director'))
  }

  const toggleAegInline = () => {
    setActivePopup((prev) => (prev === 'aeg' ? null : 'aeg'))
    setShowMarketplace(false)
    setShowIdeaCanvas(false)
  }

  const renderPopupContent = () => {
    if (activePopup === 'learning') return <LearningMode projectId={currentProjectId} />
    if (activePopup === 'logs') return <LogStream logs={logs} />
    if (activePopup === 'feedback') return <FeedbackPanel />
    if (activePopup === 'aeg') {
      return (
        <div className="flex h-full min-h-0 flex-col">
          <AEGView projectId={currentProjectId} onNodeSelect={setSelectedAegNodeId} agents={agents} />
        </div>
      )
    }
    if (activePopup === 'cost') return <CostOptimizerPanel projectId={currentProjectId} />
    return null
  }

  const popupTitle =
    activePopup === 'learning' ? 'Learning Assistant' :
      activePopup === 'logs' ? 'Live Logs' :
        activePopup === 'feedback' ? 'Feedback' :
          activePopup === 'aeg' ? 'Agent Execution Graph' :
            activePopup === 'cost' ? 'Cost Optimizer' : ''

  return (
    <div className="relative h-screen overflow-hidden bg-gradient-to-br from-background via-card to-surface-raised text-foreground">
      <AnimatedGridBackground theme={theme} />

      <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_hsl(var(--ember)/0.16),_transparent_58%)]" />
        <div className="absolute -top-40 -left-40 h-[600px] w-[600px] animate-drift rounded-full bg-primary/[0.1] blur-[120px]" />
        <div className="absolute -bottom-40 -right-40 h-[500px] w-[500px] animate-drift-reverse rounded-full bg-emerald-500/[0.04] blur-[100px]" />
        <div className="absolute right-1/3 top-1/3 h-64 w-64 animate-pulse-slow rounded-full bg-gradient-to-r from-amber-300/10 to-transparent blur-2xl" />
        <div className="absolute left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary/30 to-transparent animate-scan" />
      </div>

      <div
        className="pointer-events-none fixed inset-0 z-[1] opacity-[0.03] animate-grain"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='1'/%3E%3C/svg%3E\")",
        }}
      />

      <div className="relative z-10 h-full overflow-hidden">

        <aside className={`fixed left-0 top-24 z-[100] h-[calc(100vh-6rem)] ${isSidebarExpanded ? 'w-60' : 'w-20'} rounded-none border-r border-t border-primary/20 border-t-primary/35 bg-gradient-to-b from-background/92 via-card/80 to-surface-raised/70 p-3 backdrop-blur-2xl shadow-glass transition-all duration-300`}>
          <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-primary/45 via-primary/25 to-transparent" />
          <div className="pointer-events-none absolute inset-y-0 right-0 w-px bg-gradient-to-b from-primary/40 via-primary/10 to-transparent" />
          <div className="mt-6 flex h-full flex-col items-center gap-3">
            <button onClick={() => togglePopup('learning')} className={`${iconClass('learning')} group`} title="Learning Agent" aria-label="Open learning assistant panel">
              {activePopup === 'learning' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-primary" />}
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M2 8l10-4 10 4-10 4-10-4z" /><path d="M6 10v4c0 2.2 2.7 4 6 4s6-1.8 6-4v-4" />
              </svg>
              <span className={sidebarLabelClass}>Learning Assistant</span>
              {!isSidebarExpanded && <span className="pointer-events-none absolute left-full ml-3 z-50 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">Learning Assistant</span>}
            </button>
            <button onClick={() => togglePopup('logs')} className={`${iconClass('logs')} group`} title="Live Logs" aria-label="Open live logs panel">
              {activePopup === 'logs' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-primary" />}
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h8" /><path d="M8 12h8" /><path d="M8 17h5" />
              </svg>
              <span className={sidebarLabelClass}>Live Logs</span>
              {!isSidebarExpanded && <span className="pointer-events-none absolute left-full ml-3 z-50 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">Live Logs</span>}
            </button>
            <button onClick={() => togglePopup('feedback')} className={`${iconClass('feedback')} group`} title="Feedback" aria-label="Open feedback panel">
              {activePopup === 'feedback' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-primary" />}
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M4 21l4-1 10-10-3-3L5 17l-1 4z" /><path d="M14 7l3 3" />
              </svg>
              <span className={sidebarLabelClass}>Feedback</span>
              {!isSidebarExpanded && <span className="pointer-events-none absolute left-full ml-3 z-50 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">Feedback</span>}
            </button>

            <button onClick={openMarketplace} className={`relative flex h-10 ${isSidebarExpanded ? 'w-[96%] self-center gap-2.5 px-2.5 pr-3.5 overflow-visible' : 'w-10 px-2.5 overflow-hidden'} justify-start items-center rounded-xl border origin-left transition-all duration-300 border-border/55 bg-gradient-to-r from-card/90 via-card/60 to-primary/[0.08] text-foreground/80 backdrop-blur-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_10px_20px_-16px_rgba(0,0,0,0.55)] hover:border-primary/35 hover:from-card/95 hover:via-card/70 hover:to-primary/[0.14] hover:text-foreground group`} title="Agent Marketplace" aria-label="Open agent marketplace">
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <rect x="3" y="3" width="7" height="7" rx="1" />
                <rect x="14" y="3" width="7" height="7" rx="1" />
                <rect x="3" y="14" width="7" height="7" rx="1" />
                <rect x="14" y="14" width="7" height="7" rx="1" />
              </svg>
              <span className={sidebarLabelClass}>Agent Marketplace</span>
              {!isSidebarExpanded && <span className="pointer-events-none absolute left-full ml-3 z-50 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">Agent Marketplace</span>}
            </button>

            <button onClick={() => togglePopup('cost')} className={`${iconClass('cost')} group`} title="Cost Optimizer" aria-label="Open cost optimizer panel">
              {activePopup === 'cost' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-primary" />}
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <line x1="12" y1="1" x2="12" y2="23" />
                <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
              </svg>
              <span className={sidebarLabelClass}>Cost Optimizer</span>
              {!isSidebarExpanded && <span className="pointer-events-none absolute left-full ml-3 z-50 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">Cost Optimizer</span>}
            </button>
            <div className="mt-auto flex w-full flex-col items-center gap-3">
              <button
                onClick={toggleDirectorPane}
                className={`relative flex h-10 ${isSidebarExpanded ? 'w-[96%] self-center gap-2.5 px-2.5 pr-3.5 overflow-visible' : 'w-10 px-2.5 overflow-hidden'} justify-start items-center rounded-xl border origin-left transition-all duration-300 ${hiddenPane !== 'director'
                  ? 'border-primary/60 bg-gradient-to-r from-primary/30 to-primary/10 text-primary shadow-glow-sm'
                  : 'border-border/55 bg-gradient-to-r from-card/90 via-card/60 to-primary/[0.08] text-foreground/80 backdrop-blur-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_10px_20px_-16px_rgba(0,0,0,0.55)] hover:border-primary/35 hover:from-card/95 hover:via-card/70 hover:to-primary/[0.14] hover:text-foreground'
                  } group`}
                title="Toggle Director Agent Pane"
                aria-label="Toggle director agent pane"
              >
                {hiddenPane !== 'director' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-primary" />}
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <rect x="3" y="4" width="18" height="16" rx="2" />
                  <path d="M7 9h10" />
                  <path d="M7 13h7" />
                </svg>
                <span className={sidebarLabelClass}>Director Agent</span>
                {!isSidebarExpanded && <span className="pointer-events-none absolute left-full ml-3 z-50 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">Director Agent</span>}
              </button>
              <button
                onClick={togglePreviewPane}
                className={`relative flex h-10 ${isSidebarExpanded ? 'w-[96%] self-center gap-2.5 px-2.5 pr-3.5 overflow-visible' : 'w-10 px-2.5 overflow-hidden'} justify-start items-center rounded-xl border origin-left transition-all duration-300 ${hiddenPane !== 'preview'
                  ? 'border-primary/60 bg-gradient-to-r from-primary/30 to-primary/10 text-primary shadow-glow-sm'
                  : 'border-border/55 bg-gradient-to-r from-card/90 via-card/60 to-primary/[0.08] text-foreground/80 backdrop-blur-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_10px_20px_-16px_rgba(0,0,0,0.55)] hover:border-primary/35 hover:from-card/95 hover:via-card/70 hover:to-primary/[0.14] hover:text-foreground'
                  } group`}
                title="Toggle Preview Pane"
                aria-label="Toggle preview pane"
              >
                {hiddenPane !== 'preview' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-primary" />}
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <rect x="3" y="4" width="18" height="12" rx="2" />
                  <path d="M8 20h8" />
                  <path d="M12 16v4" />
                </svg>
                <span className={sidebarLabelClass}>Preview Pane</span>
                {!isSidebarExpanded && <span className="pointer-events-none absolute left-full ml-3 z-50 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">Preview Pane</span>}
              </button>
              <button
                onClick={toggleAegInline}
                className={`relative flex h-10 ${isSidebarExpanded ? 'w-[96%] self-center gap-2.5 px-2.5 pr-3.5 overflow-visible' : 'w-10 px-2.5 overflow-hidden'} justify-start items-center rounded-xl border origin-left transition-all duration-300 ${activePopup === 'aeg'
                  ? 'border-primary/60 bg-gradient-to-r from-primary/30 to-primary/10 text-primary shadow-glow-sm'
                  : 'border-border/55 bg-gradient-to-r from-card/90 via-card/60 to-primary/[0.08] text-foreground/80 backdrop-blur-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_10px_20px_-16px_rgba(0,0,0,0.55)] hover:border-primary/35 hover:from-card/95 hover:via-card/70 hover:to-primary/[0.14] hover:text-foreground'
                  } group`}
                title="AEG"
                aria-label="Toggle AEG panel"
              >
                {activePopup === 'aeg' && <span className="absolute -left-2 h-6 w-1 rounded-full bg-primary" />}
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <circle cx="6" cy="6" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="12" cy="18" r="2" />
                  <path d="M8 7l3 9" /><path d="M16 7l-3 9" /><path d="M8 6h8" />
                </svg>
                <span className={sidebarLabelClass}>Agent Execution Graph</span>
                {!isSidebarExpanded && <span className="pointer-events-none absolute left-full ml-3 z-50 whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground opacity-0 transition-opacity group-hover:opacity-100">Agent Execution Graph</span>}
              </button>
              <button
                onClick={() => setIsSidebarExpanded((prev) => !prev)}
                className="mb-4 -mr-2 mt-1 flex h-8 w-8 items-center justify-center self-end text-foreground/60 transition-colors duration-200 hover:text-foreground"
                title={isSidebarExpanded ? 'Collapse Sidebar' : 'Expand Sidebar'}
                aria-label={isSidebarExpanded ? 'Collapse sidebar' : 'Expand sidebar'}
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  {isSidebarExpanded ? <path d="M15 6l-6 6 6 6" /> : <path d="M9 6l6 6-6 6" />}
                </svg>
              </button>
            </div>
          </div>
        </aside>

        <div className={`relative flex h-full min-h-0 flex-col ${isSidebarExpanded ? 'pl-60' : 'pl-20'} pt-24 transition-all duration-300`}>
          <header className="fixed left-0 right-0 top-0 z-[140] animate-fade-in">
            <div className="workshop-panel !bg-transparent !border-0 px-4 py-3">
              <div className="relative flex items-center justify-between gap-4">
                <div className="min-w-[280px] flex-1">
                  <p className="mono text-xs uppercase tracking-[0.35em] text-primary/80">AGENTIC NEXUS</p>
                  <div className="mt-1 flex flex-wrap items-center gap-3">
                    <h1 className="text-3xl font-display font-bold uppercase tracking-tight text-foreground md:text-4xl">Command Center</h1>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-foreground/70">
                    {selectedAegNodeId && (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/25 bg-primary/8 px-2.5 py-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                        <span className="mono font-semibold text-primary text-[11px]">Layer: {selectedAegNodeId}</span>
                      </span>
                    )}
                  </div>
                </div>

                <div ref={projectMenuRef} className="absolute left-1/2 top-1/2 z-[150] -translate-x-1/2 -translate-y-1/2">
                  <button
                    type="button"
                    onClick={() => setIsProjectMenuOpen((prev) => !prev)}
                    className={`group inline-flex min-w-[360px] items-center gap-3 rounded-2xl border-2 px-3.5 py-2 text-left shadow-lg backdrop-blur-md transition-all duration-200 ${isProjectSwitching ? 'border-primary/70 bg-gradient-to-r from-primary/20 via-card/90 to-secondary/80 ring-2 ring-primary/35' : 'border-primary/40 bg-gradient-to-r from-secondary/90 via-card/90 to-secondary/75 hover:border-primary/60'}`}
                    aria-label="Open project switcher"
                    aria-expanded={isProjectMenuOpen}
                  >
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-primary/25 bg-primary/12 text-primary">
                      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <rect x="3" y="4" width="18" height="16" rx="2" />
                        <path d="M7 9h10" />
                        <path d="M7 13h7" />
                      </svg>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="mb-0.5 flex items-center gap-2">
                        <span className="mono text-[10px] font-semibold uppercase tracking-[0.14em] text-primary/90">Project Switcher</span>
                        <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${getAgentStateClasses(activeProjectState)}`}>{activeProjectState}</span>
                        <span className="mono text-[10px] text-foreground/65">{activeProjectProgress}%</span>
                      </div>
                      <p className="truncate font-mono text-xs font-semibold text-foreground">{currentProjectName || 'Select Project...'}</p>
                    </div>
                    <svg className={`h-4 w-4 text-primary/80 transition-transform ${isProjectMenuOpen ? 'rotate-180' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </button>

                  {isProjectMenuOpen && (
                    <div className="absolute left-0 right-0 top-[calc(100%+0.45rem)] rounded-2xl border border-primary/35 bg-card/95 p-2 shadow-2xl backdrop-blur-xl">
                      <div className="mb-1 flex items-center justify-between px-1.5">
                        <p className="mono text-[10px] uppercase tracking-[0.14em] text-foreground/60">Available Projects</p>
                        <span className="text-[10px] text-foreground/50">{agents.length}</span>
                      </div>
                      <div className="max-h-72 space-y-1 overflow-auto pr-1">
                        {agents.length === 0 && (
                          <div className="rounded-xl border border-border bg-secondary/50 px-3 py-2 text-xs text-foreground/70">No projects available</div>
                        )}
                        {agents.map((agent) => {
                          const isActive = agent.id === currentProjectId
                          const progress = Math.max(0, Math.min(100, Math.round(agent.progress ?? 0)))
                          return (
                            <button
                              key={agent.id}
                              type="button"
                              onClick={() => switchProject(agent.id, 'manual')}
                              className={`w-full rounded-xl border px-3 py-2 text-left transition ${isActive ? 'border-primary/55 bg-primary/12' : 'border-border bg-card/80 hover:border-primary/40 hover:bg-secondary/60'}`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <p className="truncate font-mono text-xs font-semibold text-foreground">{agent.name}</p>
                                <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${getAgentStateClasses(agent.state)}`}>{agent.state}</span>
                              </div>
                              <div className="mt-1 flex items-center justify-between gap-2">
                                <span className="truncate text-[10px] text-foreground/55">{agent.id}</span>
                                <span className="mono text-[10px] text-foreground/70">{progress}% complete</span>
                              </div>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>


                <div className="animate-slide-in-right relative flex items-center gap-3">
                  <div
                    className="inline-flex h-12 items-center gap-2 rounded-2xl border border-border bg-card/80 px-3 text-foreground/80 backdrop-blur-sm"
                    title={`SignalR: ${connectionState}`}
                    aria-label={`SignalR connection ${connectionState}`}
                  >
                    <span className={`h-2.5 w-2.5 rounded-full shadow-lg transition-all ${connectionState === 'connected' ? 'bg-emerald-500 shadow-green-500/50 animate-glow-pulse' : connectionState === 'reconnecting' ? 'bg-amber-500 shadow-amber-500/50 animate-pulse' : 'bg-red-500/70'}`} />
                    <span className="mono text-[10px] font-semibold uppercase tracking-[0.12em] text-foreground/70">SignalR</span>
                  </div>
                  <button
                    onClick={toggleTheme}
                    className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-card/80 text-foreground/80 backdrop-blur-sm transition hover:bg-card"
                    title="Toggle theme"
                    aria-label="Toggle theme"
                  >
                    <span className="text-lg">{theme === 'dark' ? '☀' : '☾'}</span>
                  </button>
                  <CostTicker projectId={currentProjectId} />
                  <button
                    onClick={() => setIsProfileOpen((prev) => !prev)}
                    className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-card/80 text-foreground/80 backdrop-blur-sm transition hover:bg-card"
                    title="Account"
                    aria-label="Open account menu"
                  >
                    {/* ← Show Google profile photo if available */}
                    {user?.photoURL
                      ? <img src={user.photoURL} alt="profile" className="h-8 w-8 rounded-full" />
                      : <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="8" r="4" /><path d="M4 20a8 8 0 0 1 16 0" /></svg>
                    }
                  </button>

                  {isProfileOpen && (
                    <div className="absolute right-0 top-14 z-[120] w-80 rounded-2xl border border-border bg-card p-4 shadow-2xl backdrop-blur-md">
                      <div className="mb-3 flex items-center justify-between">
                        <h3 className="text-sm font-bold text-foreground">Account</h3>
                        <button onClick={() => setIsProfileOpen(false)} className="rounded-md border border-border bg-secondary px-2 py-1 text-xs text-foreground/80 hover:bg-accent">Close</button>
                      </div>
                      <div className="space-y-2 text-sm text-foreground/70">
                        {/* ← Show real user info from Firebase */}
                        <p>Signed in as: <span className="mono font-semibold text-foreground">{user?.displayName || user?.email}</span></p>
                        <p>Active Project: <span className="mono font-semibold text-foreground">{currentProjectName}</span></p>
                        <p>Project ID: <span className="mono font-semibold text-foreground">{currentProjectId || 'N/A'}</span></p>
                      </div>
                      {/* ← Sign out button */}
                      <button
                        onClick={handleLogout}
                        className="mt-4 w-full rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm font-semibold text-destructive hover:bg-destructive/20 transition"
                      >
                        Sign Out
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </header>

          {projectSwitchNotice && (
            <div className="pointer-events-none fixed left-1/2 top-24 z-[145] -translate-x-1/2 animate-fade-in">
              <div className="inline-flex items-center gap-2 rounded-xl border border-primary/35 bg-card/95 px-3 py-1.5 shadow-xl backdrop-blur-lg">
                <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                <span className="mono text-[10px] font-semibold uppercase tracking-[0.14em] text-primary/90">Switched Project</span>
                <span className="font-mono text-xs font-semibold text-foreground">{projectSwitchNotice.name}</span>
                <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${getAgentStateClasses(projectSwitchNotice.state)}`}>{projectSwitchNotice.state}</span>
                <span className="mono text-[10px] text-foreground/70">{projectSwitchNotice.progress}%</span>
              </div>
            </div>
          )}

          <main className={`relative z-10 flex-1 min-h-0 transition-all duration-500 ${isProjectSwitching ? 'ring-2 ring-primary/25 ring-inset' : ''}`}>
            <div className="flex h-full min-h-0 items-stretch gap-0">
              {activePopup && (
                <aside className={`workshop-panel !bg-transparent ${activePopup === 'aeg' ? 'w-[500px]' : 'w-[430px]'} animate-fade-in flex flex-col shadow-glass`}>
                  <div className="border-b border-border p-5">
                    <div className="flex items-center justify-between">
                      <h2 className="text-lg font-bold text-foreground">{popupTitle}</h2>
                      <button onClick={closePopup} className="workshop-btn px-3 py-1.5 text-[10px]">Close</button>
                    </div>
                  </div>
                  <div className="min-h-0 flex-1 overflow-auto p-5">{renderPopupContent()}</div>
                </aside>
              )}

              <section id="workspace-split-container" className="relative flex h-full min-h-0 flex-1">
                <div className="flex w-full items-stretch gap-0">
                  {hiddenPane !== 'director' && (
                    <div style={{ width: hiddenPane === 'preview' ? '100%' : `${splitPercent}%` }} className="workshop-panel !bg-transparent flex min-w-0 min-h-0 flex-col p-6 shadow-glass">
                      <div className="mb-4 flex items-center gap-3">
                        <div className="h-10 w-1 rounded-full bg-gradient-to-b from-primary to-orange-400" />
                        <h2 className="text-xl font-bold text-foreground">Director Agent</h2>
                      </div>
                      <div className="min-h-0 flex-1 animate-fade-in">
                        <Conversation
                          projectId={currentProjectId}
                          onProjectChange={(projectId) => switchProject(projectId, 'director')}
                          onOpenIdeaCanvas={openIdeaCanvas}
                          onExecuteProject={handleExecuteProject}
                        />
                      </div>
                    </div>
                  )}

                  {hiddenPane === 'none' && (
                    <div className={`relative z-10 flex w-3 cursor-col-resize items-center justify-center bg-transparent ${isResizing ? 'opacity-100' : 'opacity-80 hover:opacity-100'}`} onMouseDown={() => setIsResizing(true)} title="Drag to resize">
                      <div className="h-full w-[2px] bg-gradient-to-b from-primary/40 via-primary/70 to-primary/40" />
                      <div className="absolute flex -translate-y-1/2 flex-col gap-1 rounded-xl border border-border bg-card p-1 backdrop-blur-sm">
                        <button onClick={() => { setHiddenPane('preview') }} className="rounded-md px-1.5 py-0.5 text-[10px] text-foreground/70 hover:bg-accent" title="Show director only">
                          <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6" /></svg>
                        </button>
                        <button onClick={() => setSplitPercent(50)} className="rounded-md px-1.5 py-0.5 text-[10px] text-foreground/70 hover:bg-accent" title="Reset split">
                          <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 12a8 8 0 1 1-2.34-5.66" /><path d="M20 4v8h-8" /></svg>
                        </button>
                        <button onClick={() => setHiddenPane('director')} className="rounded-md px-1.5 py-0.5 text-[10px] text-foreground/70 hover:bg-accent" title="Show preview only">
                          <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6" /></svg>
                        </button>
                      </div>
                    </div>
                  )}

                  {hiddenPane !== 'preview' && (
                    <div style={{ width: hiddenPane === 'director' ? '100%' : `${100 - splitPercent}%` }} className="flex min-w-0 min-h-0 flex-col gap-0">
                      <div className="workshop-panel !bg-transparent flex min-w-0 min-h-0 flex-col p-6 shadow-glass flex-1">
                        <div className="mb-4 flex items-center gap-3">
                          <div className="h-10 w-1 rounded-full bg-gradient-to-b from-foreground/70 to-foreground/40" />
                          <h2 className="text-xl font-bold text-foreground">Preview</h2>
                        </div>
                        <div className="min-h-0 flex-1 animate-fade-in">
                          <Preview
                            currentProjectId={currentProjectId}
                            projectData={currentProjectData}
                            compactInfo={false}
                          />
                        </div>
                      </div>
                    </div>
                  )}

                </div>
              </section>
            </div>
          </main>
        </div>
      </div>

      {/* ── Agent Marketplace full-page overlay ─────────────────────────── */}
      {showMarketplace && (
        <AgentMarketplace
          onBack={() => setShowMarketplace(false)}
          selectedAegNodeId={selectedAegNodeId}
          currentProjectId={currentProjectId}
          onAgentSelected={({ agentId, aegNodeId, projectId }) => {
            console.log(`[Marketplace] ${agentId} → node ${aegNodeId} | project ${projectId}`)
          }}
        />
      )}

      {showIdeaCanvas && (
        <div className="fixed inset-0 z-[130] flex flex-col bg-gradient-to-br from-background via-card to-surface-raised p-4">
          <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-card/80 px-4 py-3 backdrop-blur-md shadow-glass">
            <div>
              <p className="mono text-[11px] uppercase tracking-[0.25em] text-primary/80">Director Workspace</p>
              <h2 className="text-lg font-bold text-foreground">Idea Canvas</h2>
            </div>
            <div className="flex items-center gap-3">
              <span className={`inline-flex items-center rounded-lg border px-2.5 py-1 text-xs font-semibold ${canvasSaveClasses}`}>
                {canvasSaveLabel}
              </span>
              <button
                onClick={() => setShowIdeaCanvas(false)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-red-500/45 bg-red-500/12 text-red-300 transition hover:bg-red-500/20"
                title="Close Canvas"
                aria-label="Close Canvas"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18" />
                  <path d="M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1 pt-3">
            <IdeaCanvas
              projectId={currentProjectId}
              isFullscreen
              onSaveStatusChange={setCanvasSaveState}
            />
          </div>
        </div>
      )}
    </div>
  )
}
