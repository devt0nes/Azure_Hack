/**
 * AgentMarketplace.jsx
 * ---------------------
 * Full-page Agent Marketplace — Azure Marketplace-style grid.
 * Matches App.jsx design tokens: ember / orange-400 / ink / midnight / sand / haze
 *
 * Layout:
 *  - Top bar: back button + title + search
 *  - Filter chips: All / Tier 1 Module / Tier 2 Support + tag pills
 *  - Card grid: icon · name · creator · type badge · description · reputation · "+ Add" button
 */

import { useState, useEffect, useCallback } from 'react'
import { getAgentCatalog, selectAgentForNode, deselectAgentForProject, getSelectedAgents } from '../services/agents.js'

// ─── Icons (reused from AgentLibraryPanel) ─────────────────────────────────
const BackendIcon   = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="2" y="3" width="20" height="4" rx="1"/><rect x="2" y="10" width="20" height="4" rx="1"/><rect x="2" y="17" width="20" height="4" rx="1"/><circle cx="6" cy="5" r="1" fill="currentColor"/><circle cx="6" cy="12" r="1" fill="currentColor"/><circle cx="6" cy="19" r="1" fill="currentColor"/></svg>
const FrontendIcon  = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/><path d="M7 8l3 3-3 3"/><path d="M13 14h4"/></svg>
const DatabaseIcon  = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 11v6c0 1.66 4.03 3 9 3s9-1.34 9-3v-6"/></svg>
const SecurityIcon  = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
const QaIcon        = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
const DevopsIcon    = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12"/></svg>
const HealerIcon    = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M11 2a2 2 0 0 0-2 2v5H4a2 2 0 0 0-2 2v2c0 1.1.9 2 2 2h5v5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2v-5h5a2 2 0 0 0 2-2v-2a2 2 0 0 0-2-2h-5V4a2 2 0 0 0-2-2z"/></svg>
const CostIcon      = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
const ArchitectIcon = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
const ApiIcon       = () => <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M8 9l-3 3 3 3"/><path d="M16 9l3 3-3 3"/><path d="M12 6l-2 12"/></svg>

function AgentIcon({ role }) {
  const r = (role || '').toLowerCase()
  if (r.includes('backend'))    return <BackendIcon />
  if (r.includes('frontend'))   return <FrontendIcon />
  if (r.includes('database'))   return <DatabaseIcon />
  if (r.includes('security'))   return <SecurityIcon />
  if (r.includes('qa'))         return <QaIcon />
  if (r.includes('devops'))     return <DevopsIcon />
  if (r.includes('healer'))     return <HealerIcon />
  if (r.includes('cost'))       return <CostIcon />
  if (r.includes('architect'))  return <ArchitectIcon />
  if (r.includes('api'))        return <ApiIcon />
  return <ArchitectIcon />
}

// Icon bg colours per role
function iconBg(role) {
  const r = (role || '').toLowerCase()
  if (r.includes('backend'))    return 'from-sky-400/20    to-sky-500/10    text-sky-600    border-sky-200/60'
  if (r.includes('frontend'))   return 'from-violet-400/20 to-violet-500/10 text-violet-600 border-violet-200/60'
  if (r.includes('database'))   return 'from-teal-400/20   to-teal-500/10   text-teal-600   border-teal-200/60'
  if (r.includes('security'))   return 'from-red-400/20    to-red-500/10    text-red-600    border-red-200/60'
  if (r.includes('qa'))         return 'from-emerald-400/20 to-emerald-500/10 text-emerald-600 border-emerald-200/60'
  if (r.includes('devops'))     return 'from-amber-400/20  to-amber-500/10  text-amber-600  border-amber-200/60'
  if (r.includes('healer'))     return 'from-pink-400/20   to-pink-500/10   text-pink-600   border-pink-200/60'
  if (r.includes('cost'))       return 'from-ember/20      to-orange-400/10 text-ember      border-ember/20'
  if (r.includes('architect'))  return 'from-indigo-400/20 to-indigo-500/10 text-indigo-600 border-indigo-200/60'
  if (r.includes('api'))        return 'from-cyan-400/20   to-cyan-500/10   text-cyan-600   border-cyan-200/60'
  return                               'from-ink/10        to-ink/5         text-ink/60     border-ink/10'
}

// ─── Reputation bar ─────────────────────────────────────────────────────────
function ReputationBar({ score }) {
  const pct   = Math.round((score || 0) * 100)
  const color = pct >= 90 ? 'from-emerald-400 to-emerald-500'
              : pct >= 80 ? 'from-amber-400 to-amber-500'
              :             'from-red-400 to-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-ink/10 overflow-hidden">
        <div className={`h-full rounded-full bg-gradient-to-r ${color} transition-all duration-700`} style={{ width: `${pct}%` }} />
      </div>
      <span className="mono text-[10px] font-semibold text-ink/50">{pct}%</span>
    </div>
  )
}

// ─── Model pill ──────────────────────────────────────────────────────────────
const MODEL_STYLES = {
  'Phi-4':               'bg-sky-100    text-sky-700    border-sky-200',
  'GPT-4o-mini':         'bg-violet-100 text-violet-700 border-violet-200',
  'GPT-4o':              'bg-ember/10   text-ember      border-ember/20',
  'GPT-4o + o1-preview': 'bg-orange-100 text-orange-700 border-orange-200',
}
function ModelPill({ label }) {
  const style = MODEL_STYLES[label] || 'bg-ink/10 text-ink/60 border-ink/10'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide ${style}`}>
      {label}
    </span>
  )
}

// ─── Tier badge ──────────────────────────────────────────────────────────────
function TierBadge({ tier }) {
  return tier === 1
    ? <span className="rounded-full bg-ember/10 border border-ember/20 px-2 py-0.5 text-[10px] font-bold text-ember tracking-wide">MODULE · T1</span>
    : <span className="rounded-full bg-ink/8 border border-ink/15 px-2 py-0.5 text-[10px] font-bold text-ink/45 tracking-wide">SUPPORT · T2</span>
}

// ─── Marketplace card ────────────────────────────────────────────────────────
function MarketplaceCard({ agent, onToggle, isAdded, canRemove }) {
  const [adding, setAdding] = useState(false)
  const [msg,    setMsg]    = useState(null)

  const handleToggle = useCallback(async () => {
    setAdding(true)
    try {
      await onToggle(agent.id)
      setMsg({ type: 'ok', text: isAdded ? 'Removed ✓' : 'Added ✓' })
      setTimeout(() => setMsg(null), 2500)
    } catch (err) {
      setMsg({ type: 'err', text: err.message })
      setTimeout(() => setMsg(null), 3000)
    } finally {
      setAdding(false)
    }
  }, [agent.id, isAdded, onToggle])

  const bg = iconBg(agent.role)

  return (
    <div className={`group flex flex-col rounded-2xl border transition-all duration-200 overflow-hidden ${
      isAdded
        ? 'border-ember/40 bg-gradient-to-br from-ember/5 via-white/90 to-orange-400/5 shadow-md'
        : 'border-white/50 bg-white/75 hover:border-white/80 hover:bg-white/95 hover:shadow-lg'
    }`}>

      {/* Card body — grows to fill */}
      <div className="flex flex-col gap-3 p-5 flex-1">

        {/* Icon + badges row */}
        <div className="flex items-start justify-between gap-3">
          <div className={`flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-2xl border bg-gradient-to-br ${bg} transition-transform duration-200 group-hover:scale-105`}>
            <AgentIcon role={agent.role} />
          </div>
          <div className="flex flex-col items-end gap-1">
            <TierBadge tier={agent.tier} />
            <ModelPill label={agent.model_label} />
          </div>
        </div>

        {/* Name + creator */}
        <div>
          <h3 className="text-sm font-bold text-midnight leading-tight">{agent.role}</h3>
          <p className="mt-0.5 text-[11px] text-ink/45 font-medium">Agentic Nexus</p>
        </div>

        {/* Type label (like "Virtual Machine" in Azure) */}
        <p className="text-[10px] font-bold uppercase tracking-widest text-ink/30">
          {agent.tier === 1 ? 'Module Agent' : 'Support Agent'}
        </p>

        {/* Description */}
        <p className="text-xs leading-relaxed text-ink/65 flex-1">
          {agent.description
            ? agent.description.length > 110
              ? agent.description.slice(0, 110) + '…'
              : agent.description
            : 'Specialized AI agent for intelligent task execution.'}
        </p>

        {/* Reputation */}
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-ink/30">Reputation</p>
          <ReputationBar score={agent.reputation_score} />
        </div>

        {/* Tags */}
        {agent.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {agent.tags.slice(0, 4).map(tag => (
              <span key={tag} className="rounded-full bg-ink/5 border border-ink/8 px-2 py-0.5 text-[10px] font-medium text-ink/45">
                #{tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Footer — "+ Add" button, always at bottom */}
      <div className="border-t border-ink/8 px-5 py-3 flex items-center justify-between gap-3">
        {msg ? (
          <p className={`text-[11px] font-semibold ${msg.type === 'ok' ? 'text-emerald-600' : 'text-red-500'}`}>
            {msg.text}
          </p>
        ) : (
          <span className="text-[11px] text-ink/30">{isAdded ? 'In use' : 'Available'}</span>
        )}

        <button
          onClick={handleToggle}
          disabled={adding || (isAdded && !canRemove)}
          className={`flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold transition-all duration-150 ${
            isAdded
              ? 'bg-white border border-red-200 text-red-600 hover:bg-red-50'
              : 'bg-gradient-to-r from-ember to-orange-400 text-white shadow-sm hover:shadow-md hover:opacity-90'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          {adding ? (
            <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
            </svg>
          ) : isAdded ? (
            <>
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg>
              Remove
            </>
          ) : (
            <>
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 5v14M5 12h14"/></svg>
              + Add
            </>
          )}
        </button>
      </div>
    </div>
  )
}

// ─── Main Marketplace Page ───────────────────────────────────────────────────
export default function AgentMarketplace({ onBack, selectedAegNodeId, onAgentSelected, currentProjectId }) {
  const [agents,     setAgents]     = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [search,     setSearch]     = useState('')
  const [tierFilter, setTierFilter] = useState('all')
  const [activeTag,  setActiveTag]  = useState(null)
  const [addedIds,   setAddedIds]   = useState(new Set())
  const [showCustomAgentNote, setShowCustomAgentNote] = useState(false)

  // Load catalog
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true); setError(null)
      try {
        const data = await getAgentCatalog()
        if (!cancelled) setAgents(data.agents || [])
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  // Pre-mark agents already selected for this project
  useEffect(() => {
    if (!currentProjectId) return
    let cancelled = false
    const loadSelected = async () => {
      try {
        const data = await getSelectedAgents(currentProjectId)
        if (!cancelled && data.selected_agents?.length > 0) {
          const ids = new Set(data.selected_agents.map(a => a.id || a.agent_id))
          setAddedIds(ids)
        }
      } catch {
        // non-fatal — just won't pre-mark
      }
    }
    loadSelected()
    return () => { cancelled = true }
  }, [currentProjectId])

  const allTags = [...new Set(agents.flatMap(a => a.tags || []))].sort()
  const selectedAgents = agents
    .filter(agent => addedIds.has(agent.id))
    .sort((a, b) => a.role.localeCompare(b.role))

  const filtered = agents.filter(a => {
    const matchesTier   = tierFilter === 'all' || a.tier === tierFilter
    const matchesSearch = !search || a.role.toLowerCase().includes(search.toLowerCase()) || (a.description || '').toLowerCase().includes(search.toLowerCase())
    const matchesTag    = !activeTag || (a.tags || []).includes(activeTag)
    return matchesTier && matchesSearch && matchesTag
  })

  const handleToggleAgent = useCallback(async (agentId) => {
    if (addedIds.has(agentId)) {
      if (!currentProjectId) {
        throw new Error('Select a project before removing agents')
      }
      await deselectAgentForProject({
        projectId: currentProjectId,
        agentId,
      })
      setAddedIds(prev => {
        const next = new Set(prev)
        next.delete(agentId)
        return next
      })
      return
    }

    await selectAgentForNode({
      aegNodeId: selectedAegNodeId || 'unassigned',
      agentId,
      projectId: currentProjectId || null,
    })
    setAddedIds(prev => new Set([...prev, agentId]))
    onAgentSelected?.({ agentId, aegNodeId: selectedAegNodeId, projectId: currentProjectId })
  }, [addedIds, selectedAegNodeId, currentProjectId, onAgentSelected])

  return (
    <div className="fixed inset-0 z-[100] overflow-hidden bg-gradient-to-br from-sand via-white to-haze flex flex-col">

      {/* Background decorations */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(242,106,46,0.12),_transparent_55%)]" />
        <div className="absolute -right-32 top-0 h-96 w-96 rounded-full bg-gradient-to-br from-ember/10 via-orange-400/8 to-transparent blur-3xl" />
        <div className="absolute -left-32 bottom-0 h-80 w-80 rounded-full bg-gradient-to-tr from-emerald-500/8 to-transparent blur-3xl" />
      </div>

      {/* ── Header — matches Command Center style ────────────────────────── */}
      <header className="relative z-10 flex-shrink-0 animate-fade-in px-6 pt-4">
        <div className="rounded-3xl border border-white/30 bg-gradient-to-br from-white/80 via-white/65 to-white/50 p-4 shadow-glass backdrop-blur-md">
          <div className="flex flex-wrap items-start justify-between gap-4">

            {/* Left: back + title */}
            <div className="min-w-[280px] flex-1 flex items-start gap-4">
              <button
                onClick={onBack}
                className="mt-1 flex items-center gap-2 rounded-xl border border-white/50 bg-white/70 px-3 py-2 text-xs font-semibold text-ink/70 transition hover:bg-white hover:text-ink hover:border-white/80 shadow-sm flex-shrink-0"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
                Back
              </button>
              <div>
                <p className="mono text-xs uppercase tracking-[0.35em] bg-gradient-to-r from-ember to-orange-400 bg-clip-text text-transparent font-bold">PLATFORM A</p>
                <h1 className="mt-1 text-3xl md:text-4xl font-bold bg-gradient-to-r from-midnight via-ink to-midnight bg-clip-text text-transparent leading-tight">Agent Marketplace</h1>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink/70">
                  <span className="inline-flex items-center rounded-full border border-white/30 bg-white/70 px-2.5 py-1">
                    Browse and add specialized AI agents to your workflow
                  </span>
                  <span className="inline-flex items-center rounded-full border border-white/30 bg-white/70 px-2.5 py-1">
                    Agents: <span className="mono ml-1 font-semibold text-ink">{agents.length}</span>
                  </span>
                  {addedIds.size > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      <span className="mono font-semibold text-emerald-700 text-[11px]">
                        {addedIds.size} agent{addedIds.size !== 1 ? 's' : ''} selected for this project
                      </span>
                    </span>
                  )}
                  {selectedAegNodeId && (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-ember/25 bg-ember/8 px-2.5 py-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-ember animate-pulse" />
                      <span className="mono font-semibold text-ember text-[11px]">Node: {selectedAegNodeId}</span>
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Right: search */}
            <div className="animate-slide-in-right flex items-start gap-3 pt-1">
              <button
                onClick={() => setShowCustomAgentNote(prev => !prev)}
                className="inline-flex items-center gap-2 rounded-xl border border-ember/25 bg-ember/8 px-3 py-2 text-xs font-semibold text-ember shadow-sm transition hover:bg-ember/12"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M12 5v14M5 12h14" />
                </svg>
                Upload Custom Agent
              </button>
              <div className="relative w-64">
                <svg className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink/30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                </svg>
                <input
                  type="text"
                  placeholder="Search agents…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="w-full rounded-xl border border-white/50 bg-white/80 py-2 pl-8 pr-3 text-xs text-ink placeholder-ink/30 outline-none focus:border-ember/30 focus:ring-1 focus:ring-ember/20 transition shadow-sm"
                />
              </div>
            </div>

          </div>
        </div>
      </header>

      {showCustomAgentNote && (
        <div className="relative z-10 px-6 pt-2">
          <div className="rounded-2xl border border-ember/20 bg-white/80 p-4 shadow-glass backdrop-blur-md">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="max-w-3xl">
                <p className="text-sm font-semibold text-midnight">Custom agent upload is the next step</p>
                <p className="mt-1 text-xs leading-relaxed text-ink/65">
                  The UI now exposes the entry point, but submission is intentionally disabled while we finish the backend workflow.
                  We have already prepared the catalog storage model so future user-created agents can live beside built-ins in Cosmos DB.
                </p>
              </div>
              <button
                onClick={() => setShowCustomAgentNote(false)}
                className="rounded-lg bg-ink/5 px-3 py-1.5 text-xs font-medium text-ink/70 transition hover:bg-ink/10 hover:text-ink"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Filter bar — two dropdowns ───────────────────────────────────── */}
      <div className="relative z-10 flex-shrink-0 px-6 py-3">
        <div className="flex items-center gap-3">

          {/* Tier dropdown */}
          <div className="relative">
            <select
              value={tierFilter}
              onChange={e => setTierFilter(e.target.value === '1' ? 1 : e.target.value === '2' ? 2 : 'all')}
              className="appearance-none rounded-xl border border-white/50 bg-white/80 py-2 pl-3 pr-8 text-xs font-semibold text-ink shadow-sm outline-none focus:border-ember/30 focus:ring-1 focus:ring-ember/20 transition cursor-pointer backdrop-blur-sm"
            >
              <option value="all">All Agents</option>
              <option value="1">Module Agents (T1)</option>
              <option value="2">Support Agents (T2)</option>
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 9l6 6 6-6"/></svg>
          </div>

          {/* Tag dropdown */}
          <div className="relative">
            <select
              value={activeTag || ''}
              onChange={e => setActiveTag(e.target.value || null)}
              className="appearance-none rounded-xl border border-white/50 bg-white/80 py-2 pl-3 pr-8 text-xs font-semibold text-ink shadow-sm outline-none focus:border-ember/30 focus:ring-1 focus:ring-ember/20 transition cursor-pointer backdrop-blur-sm"
            >
              <option value="">All Tags</option>
              {allTags.map(tag => (
                <option key={tag} value={tag}>#{tag}</option>
              ))}
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 9l6 6 6-6"/></svg>
          </div>

          {/* Active filter chips (compact summary) */}
          {(tierFilter !== 'all' || activeTag) && (
            <div className="flex items-center gap-2">
              {tierFilter !== 'all' && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-ember/25 bg-ember/8 px-2.5 py-1 text-[11px] font-semibold text-ember">
                  {tierFilter === 1 ? 'Module T1' : 'Support T2'}
                  <button onClick={() => setTierFilter('all')} className="hover:text-ember/70">×</button>
                </span>
              )}
              {activeTag && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-ember/25 bg-ember/8 px-2.5 py-1 text-[11px] font-semibold text-ember">
                  #{activeTag}
                  <button onClick={() => setActiveTag(null)} className="hover:text-ember/70">×</button>
                </span>
              )}
              <button
                onClick={() => { setTierFilter('all'); setActiveTag(null) }}
                className="text-[11px] font-medium text-ink/40 hover:text-ember transition"
              >
                Clear all
              </button>
            </div>
          )}

          {/* Count — pushed right */}
          <span className="ml-auto text-[11px] font-medium uppercase tracking-widest text-ink/30">
            {filtered.length} agent{filtered.length !== 1 ? 's' : ''}
          </span>

        </div>
      </div>

      {/* ── Scrollable grid ──────────────────────────────────────────────── */}
      <div className="relative z-10 flex-1 overflow-hidden px-6 pb-6">
        <div className="grid h-full min-h-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">

          <div className="min-h-0 overflow-y-auto px-2 py-4">

            {loading && (
              <div className="flex flex-col items-center justify-center gap-4 py-24">
                <div className="h-10 w-10 rounded-full border-2 border-ember/30 border-t-ember animate-spin" />
                <p className="text-sm font-medium text-ink/40">Loading agent catalog…</p>
              </div>
            )}

            {error && (
              <div className="mx-auto max-w-md rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
                <p className="text-sm font-semibold text-red-600">Could not load catalog</p>
                <p className="mt-1 text-xs text-red-500">{error}</p>
                <p className="mt-3 text-[11px] text-ink/40">Make sure the backend is running and <code className="mono">/api/agents</code> is reachable.</p>
              </div>
            )}

            {!loading && !error && filtered.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-3 py-24">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-ink/10 bg-white/60 text-ink/25">
                  <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                </div>
                <p className="text-sm font-semibold text-ink/40">No agents match your filters</p>
                <button onClick={() => { setSearch(''); setTierFilter('all'); setActiveTag(null) }} className="text-xs font-medium text-ember hover:underline">
                  Clear filters
                </button>
              </div>
            )}

            {!loading && !error && filtered.length > 0 && (
              <>
                {/* Tier 1 section */}
                {filtered.filter(a => a.tier === 1).length > 0 && (
                  <section className="mb-8">
                    <div className="mb-4 flex items-center gap-4">
                      <div className="h-px flex-1 bg-ember/15" />
                      <span className="text-[10px] font-black uppercase tracking-[0.3em] text-ember/60">
                        Tier 1 — Module Agents
                        <span className="ml-2 font-medium opacity-60">({filtered.filter(a => a.tier === 1).length})</span>
                      </span>
                      <div className="h-px flex-1 bg-ember/15" />
                    </div>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      {filtered.filter(a => a.tier === 1).map(agent => (
                        <MarketplaceCard
                          key={agent.id}
                          agent={agent}
                          onToggle={handleToggleAgent}
                          isAdded={addedIds.has(agent.id)}
                          canRemove={Boolean(currentProjectId)}
                        />
                      ))}
                    </div>
                  </section>
                )}

                {/* Tier 2 section */}
                {filtered.filter(a => a.tier === 2).length > 0 && (
                  <section>
                    <div className="mb-4 flex items-center gap-4">
                      <div className="h-px flex-1 bg-ink/10" />
                      <span className="text-[10px] font-black uppercase tracking-[0.3em] text-ink/30">
                        Tier 2 — Support Agents
                        <span className="ml-2 font-medium opacity-60">({filtered.filter(a => a.tier === 2).length})</span>
                      </span>
                      <div className="h-px flex-1 bg-ink/10" />
                    </div>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      {filtered.filter(a => a.tier === 2).map(agent => (
                        <MarketplaceCard
                          key={agent.id}
                          agent={agent}
                          onToggle={handleToggleAgent}
                          isAdded={addedIds.has(agent.id)}
                          canRemove={Boolean(currentProjectId)}
                        />
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </div>

          <aside className="hidden min-h-0 xl:block">
            <div className="sticky top-4 h-[calc(100vh-15rem)] rounded-3xl border border-white/40 bg-gradient-to-br from-white/90 via-white/82 to-white/70 p-5 shadow-glass backdrop-blur-md">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="mono text-[10px] font-bold uppercase tracking-[0.28em] text-ember/70">Selected</p>
                  <h2 className="mt-1 text-lg font-bold text-midnight">Project Agents</h2>
                </div>
                <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">
                  {selectedAgents.length}
                </span>
              </div>

              <p className="mt-3 text-xs leading-relaxed text-ink/55">
                Keep track of the agents already attached to this project without scrolling through the full catalog.
              </p>

              <div className="mt-5 h-[calc(100%-7rem)] overflow-y-auto pr-1">
                {selectedAgents.length === 0 ? (
                  <div className="flex h-full flex-col items-center justify-center rounded-2xl border border-dashed border-ink/10 bg-white/45 px-5 text-center">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-ink/5 text-ink/25">
                      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M12 5v14M5 12h14" />
                      </svg>
                    </div>
                    <p className="mt-4 text-sm font-semibold text-ink/45">No agents selected yet</p>
                    <p className="mt-1 text-xs text-ink/35">Added agents will appear here as a quick-access list.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {selectedAgents.map(agent => (
                      <div key={agent.id} className="rounded-2xl border border-emerald-100 bg-white/70 p-4 shadow-sm">
                        <div className="flex items-start gap-3">
                          <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-2xl border bg-gradient-to-br ${iconBg(agent.role)}`}>
                            <AgentIcon role={agent.role} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <p className="text-sm font-semibold leading-tight text-midnight">{agent.role}</p>
                                <p className="mt-0.5 text-[11px] text-ink/45">{agent.id}</p>
                              </div>
                              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700">
                                Added
                              </span>
                            </div>

                            <div className="mt-3 flex items-center justify-between gap-2">
                              <ModelPill label={agent.model_label} />
                              <button
                                onClick={() => handleToggleAgent(agent.id)}
                                className="rounded-lg border border-red-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-red-600 transition hover:bg-red-50"
                              >
                                Remove
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}
