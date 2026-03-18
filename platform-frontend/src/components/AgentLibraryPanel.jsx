/**
 * AgentLibraryPanel.jsx
 * ----------------------
 * Full Agent Library panel — shown in the left sidebar popup system.
 * Matches the existing App.jsx design tokens exactly:
 *   ember / orange-400 / ink / midnight / sand / haze / white
 *
 * Features:
 *  - Lists all agents grouped by Tier 1 (Module) / Tier 2 (Support)
 *  - Filter bar: All / Tier 1 / Tier 2 + tag chips
 *  - Search by role name
 *  - Expandable AgentCard with description, model pill, MCP tools, reputation bar
 *  - "Select for AEG node" action (calls POST /api/agents/select)
 *  - Empty & error states
 */

import { useState, useEffect, useCallback } from 'react'
import { getAgentCatalog, selectAgentForNode } from '../services/agents.js'

// ─── Reputation bar ────────────────────────────────────────────────────────
function ReputationBar({ score }) {
  const pct   = Math.round(score * 100)
  const color =
    pct >= 90 ? 'from-emerald-400 to-emerald-500' :
    pct >= 80 ? 'from-amber-400  to-amber-500'    :
                'from-red-400    to-red-500'

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-ink/10 overflow-hidden">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${color} transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="mono text-[11px] font-semibold text-ink/60">{pct}%</span>
    </div>
  )
}

// ─── Model tier pill ────────────────────────────────────────────────────────
const MODEL_STYLES = {
  'Phi-4':               'bg-sky-100   text-sky-700   border-sky-200',
  'GPT-4o-mini':         'bg-violet-100 text-violet-700 border-violet-200',
  'GPT-4o':              'bg-ember/10  text-ember     border-ember/20',
  'GPT-4o + o1-preview': 'bg-orange-100 text-orange-700 border-orange-200',
}

function ModelPill({ label }) {
  const style = MODEL_STYLES[label] || 'bg-ink/10 text-ink/70 border-ink/10'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide ${style}`}>
      {label}
    </span>
  )
}

// ─── Tier badge ─────────────────────────────────────────────────────────────
function TierBadge({ tier }) {
  return tier === 1
    ? <span className="rounded-full bg-ember/10 border border-ember/20 px-2 py-0.5 text-[10px] font-bold text-ember tracking-wide">TIER 1 · MODULE</span>
    : <span className="rounded-full bg-ink/8 border border-ink/15 px-2 py-0.5 text-[10px] font-bold text-ink/50 tracking-wide">TIER 2 · SUPPORT</span>
}

// ─── MCP tool chip ──────────────────────────────────────────────────────────
function McpChip({ tool }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-haze/80 border border-white/60 px-1.5 py-0.5 text-[10px] font-medium text-ink/60">
      <svg className="h-2.5 w-2.5 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
      </svg>
      {tool}
    </span>
  )
}

// ─── Individual Agent Card ──────────────────────────────────────────────────
function AgentCard({ agent, onSelect, selectedAegNodeId, isSelected }) {
  const [expanded,   setExpanded]   = useState(false)
  const [selecting,  setSelecting]  = useState(false)
  const [selectMsg,  setSelectMsg]  = useState(null)

  const handleSelect = useCallback(async () => {
    if (!selectedAegNodeId) {
      setSelectMsg({ type: 'warn', text: 'No AEG node targeted. Open the AEG panel and click a node first.' })
      setTimeout(() => setSelectMsg(null), 3000)
      return
    }
    setSelecting(true)
    try {
      await onSelect(agent.id)
      setSelectMsg({ type: 'ok', text: 'Assigned to node ✓' })
      setTimeout(() => setSelectMsg(null), 2500)
    } catch (err) {
      setSelectMsg({ type: 'err', text: err.message })
      setTimeout(() => setSelectMsg(null), 3000)
    } finally {
      setSelecting(false)
    }
  }, [agent.id, onSelect, selectedAegNodeId])

  return (
    <div
      className={`group rounded-2xl border transition-all duration-200 ${
        isSelected
          ? 'border-ember/40 bg-gradient-to-br from-ember/5 to-orange-400/5 shadow-sm'
          : 'border-white/50 bg-white/70 hover:border-white/80 hover:bg-white/90 hover:shadow-sm'
      }`}
    >
      {/* Card header — always visible */}
      <button
        className="w-full p-4 text-left"
        onClick={() => setExpanded(v => !v)}
        aria-expanded={expanded}
      >
        <div className="flex items-start justify-between gap-3">
          {/* Left: icon + name */}
          <div className="flex items-start gap-3">
            <div className={`mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl border transition-colors ${
              isSelected
                ? 'border-ember/30 bg-ember/10 text-ember'
                : 'border-ink/10 bg-haze/60 text-ink/50 group-hover:border-ember/20 group-hover:text-ember/70'
            }`}>
              <AgentIcon role={agent.role} />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-bold text-midnight leading-tight truncate">{agent.role}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <TierBadge tier={agent.tier} />
                <ModelPill label={agent.model_label} />
              </div>
            </div>
          </div>

          {/* Right: reputation + chevron */}
          <div className="flex flex-shrink-0 flex-col items-end gap-1.5 min-w-[80px]">
            <div className="w-20">
              <ReputationBar score={agent.reputation_score} />
            </div>
            <svg
              className={`h-3.5 w-3.5 text-ink/30 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
            >
              <path d="M6 9l6 6 6-6"/>
            </svg>
          </div>
        </div>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="border-t border-ink/8 px-4 pb-4 pt-3 space-y-3">
          {/* Description */}
          <p className="text-xs leading-relaxed text-ink/70">{agent.description}</p>

          {/* MCP tools */}
          {agent.mcp_tools?.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink/35">MCP Tools</p>
              <div className="flex flex-wrap gap-1">
                {agent.mcp_tools.map(t => <McpChip key={t} tool={t} />)}
              </div>
            </div>
          )}

          {/* Tags */}
          {agent.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {agent.tags.map(tag => (
                <span
                  key={tag}
                  className="rounded-full bg-ink/5 px-2 py-0.5 text-[10px] font-medium text-ink/50"
                >
                  #{tag}
                </span>
              ))}
            </div>
          )}

          {/* Select button */}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleSelect}
              disabled={selecting}
              className={`flex-1 rounded-xl px-3 py-2 text-xs font-semibold transition-all duration-150 ${
                isSelected
                  ? 'bg-ember text-white shadow-sm hover:bg-ember/90'
                  : 'bg-gradient-to-r from-ember/10 to-orange-400/10 border border-ember/20 text-ember hover:from-ember/15 hover:to-orange-400/15'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {selecting ? 'Assigning…' : isSelected ? '✓ Assigned' : 'Select for AEG Node'}
            </button>
          </div>

          {/* Feedback message */}
          {selectMsg && (
            <p className={`text-[11px] font-medium ${
              selectMsg.type === 'ok'   ? 'text-emerald-600' :
              selectMsg.type === 'warn' ? 'text-amber-600'   : 'text-red-500'
            }`}>
              {selectMsg.text}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Role icon (SVG, keeps things self-contained) ──────────────────────────
function AgentIcon({ role }) {
  const r = role.toLowerCase()
  if (r.includes('backend'))   return <BackendIcon />
  if (r.includes('frontend'))  return <FrontendIcon />
  if (r.includes('database'))  return <DatabaseIcon />
  if (r.includes('security'))  return <SecurityIcon />
  if (r.includes('qa'))        return <QaIcon />
  if (r.includes('devops'))    return <DevopsIcon />
  if (r.includes('healer'))    return <HealerIcon />
  if (r.includes('cost'))      return <CostIcon />
  return <DefaultIcon />
}

const BackendIcon  = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="4" rx="1"/><rect x="2" y="10" width="20" height="4" rx="1"/><rect x="2" y="17" width="20" height="4" rx="1"/><circle cx="6" cy="5" r="1" fill="currentColor"/><circle cx="6" cy="12" r="1" fill="currentColor"/><circle cx="6" cy="19" r="1" fill="currentColor"/></svg>
const FrontendIcon = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/><path d="M7 8l3 3-3 3"/><path d="M13 14h4"/></svg>
const DatabaseIcon = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 11v6c0 1.66 4.03 3 9 3s9-1.34 9-3v-6"/></svg>
const SecurityIcon = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
const QaIcon       = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
const DevopsIcon   = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12"/></svg>
const HealerIcon   = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M11 2a2 2 0 0 0-2 2v5H4a2 2 0 0 0-2 2v2c0 1.1.9 2 2 2h5v5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2v-5h5a2 2 0 0 0 2-2v-2a2 2 0 0 0-2-2h-5V4a2 2 0 0 0-2-2z"/></svg>
const CostIcon     = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
const DefaultIcon  = () => <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M3 12h3M18 12h3M12 3v3M12 18v3"/></svg>

// ─── Tier section heading ───────────────────────────────────────────────────
function TierHeading({ tier, count }) {
  return (
    <div className="flex items-center gap-3 mb-2">
      <div className={`h-px flex-1 ${tier === 1 ? 'bg-ember/20' : 'bg-ink/10'}`} />
      <span className={`text-[10px] font-black uppercase tracking-[0.25em] ${tier === 1 ? 'text-ember/70' : 'text-ink/35'}`}>
        Tier {tier} — {tier === 1 ? 'Module Agents' : 'Support Agents'}
        <span className="ml-1.5 font-medium opacity-60">({count})</span>
      </span>
      <div className={`h-px flex-1 ${tier === 1 ? 'bg-ember/20' : 'bg-ink/10'}`} />
    </div>
  )
}

// ─── Main Panel ─────────────────────────────────────────────────────────────
export default function AgentLibraryPanel({ selectedAegNodeId = null, onAgentSelected }) {
  const [agents,       setAgents]       = useState([])
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState(null)
  const [search,       setSearch]       = useState('')
  const [tierFilter,   setTierFilter]   = useState('all')   // 'all' | 1 | 2
  const [activeTag,    setActiveTag]    = useState(null)
  const [selectedId,   setSelectedId]   = useState(null)

  // ── Fetch catalog on mount ─────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoading(true)
      setError(null)
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

  // ── All unique tags across catalog ────────────────────────────────────
  const allTags = [...new Set(agents.flatMap(a => a.tags || []))].sort()

  // ── Filtered agents ───────────────────────────────────────────────────
  const filtered = agents.filter(a => {
    const matchesTier   = tierFilter === 'all' || a.tier === tierFilter
    const matchesSearch = !search || a.role.toLowerCase().includes(search.toLowerCase())
    const matchesTag    = !activeTag || (a.tags || []).includes(activeTag)
    return matchesTier && matchesSearch && matchesTag
  })

  const tier1 = filtered.filter(a => a.tier === 1)
  const tier2 = filtered.filter(a => a.tier === 2)

  // ── Handle selection ──────────────────────────────────────────────────
  const handleSelect = useCallback(async (agentId) => {
    await selectAgentForNode({
      aegNodeId: selectedAegNodeId || 'unassigned',
      agentId,
    })
    setSelectedId(agentId)
    onAgentSelected?.({ agentId, aegNodeId: selectedAegNodeId })
  }, [selectedAegNodeId, onAgentSelected])

  // ── Loading ───────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <div className="h-8 w-8 rounded-full border-2 border-ember/30 border-t-ember animate-spin" />
        <p className="text-xs font-medium text-ink/40">Loading agent catalog…</p>
      </div>
    )
  }

  // ── Error ─────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-center">
        <p className="text-sm font-semibold text-red-600">Could not load catalog</p>
        <p className="mt-1 text-xs text-red-500">{error}</p>
        <p className="mt-2 text-[11px] text-ink/40">
          Make sure the backend is running and <code className="mono">/api/agents</code> is reachable.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">

      {/* ── Active AEG node banner ──────────────────────────────────────── */}
      {selectedAegNodeId ? (
        <div className="flex items-center gap-2 rounded-xl border border-ember/25 bg-ember/6 px-3 py-2">
          <div className="h-2 w-2 rounded-full bg-ember animate-pulse" />
          <p className="text-xs font-semibold text-ember">
            Assigning to node: <span className="mono">{selectedAegNodeId}</span>
          </p>
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-xl border border-ink/10 bg-ink/3 px-3 py-2">
          <div className="h-2 w-2 rounded-full bg-ink/20" />
          <p className="text-xs text-ink/40">
            Click a node in the AEG panel to target it, then select an agent here.
          </p>
        </div>
      )}

      {/* ── Search bar ─────────────────────────────────────────────────── */}
      <div className="relative">
        <svg
          className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink/30"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        >
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
        </svg>
        <input
          type="text"
          placeholder="Search agents…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-full rounded-xl border border-white/50 bg-white/70 py-2 pl-8 pr-3 text-xs text-ink placeholder-ink/30 outline-none focus:border-ember/30 focus:ring-1 focus:ring-ember/20 transition"
        />
      </div>

      {/* ── Tier filter tabs ────────────────────────────────────────────── */}
      <div className="flex gap-1 rounded-xl border border-white/40 bg-white/50 p-1">
        {[['all', 'All'], [1, 'Module (T1)'], [2, 'Support (T2)']].map(([val, label]) => (
          <button
            key={val}
            onClick={() => setTierFilter(val)}
            className={`flex-1 rounded-lg py-1.5 text-[11px] font-semibold transition-all ${
              tierFilter === val
                ? 'bg-white shadow-sm text-ember border border-ember/20'
                : 'text-ink/50 hover:text-ink/70'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Tag pills ───────────────────────────────────────────────────── */}
      {allTags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {allTags.map(tag => (
            <button
              key={tag}
              onClick={() => setActiveTag(activeTag === tag ? null : tag)}
              className={`rounded-full border px-2 py-0.5 text-[10px] font-medium transition-all ${
                activeTag === tag
                  ? 'border-ember/30 bg-ember/10 text-ember'
                  : 'border-ink/10 bg-white/60 text-ink/50 hover:border-ink/20 hover:text-ink/70'
              }`}
            >
              #{tag}
            </button>
          ))}
        </div>
      )}

      {/* ── Results count ───────────────────────────────────────────────── */}
      <p className="text-[10px] font-medium uppercase tracking-widest text-ink/30">
        {filtered.length} agent{filtered.length !== 1 ? 's' : ''}
        {search ? ` matching "${search}"` : ''}
        {activeTag ? ` tagged #${activeTag}` : ''}
      </p>

      {/* ── Agent cards grouped by tier ─────────────────────────────────── */}
      {filtered.length === 0 ? (
        <div className="rounded-2xl border border-ink/8 bg-white/40 py-10 text-center">
          <p className="text-sm font-semibold text-ink/40">No agents match your filters</p>
          <button
            onClick={() => { setSearch(''); setTierFilter('all'); setActiveTag(null) }}
            className="mt-2 text-xs font-medium text-ember hover:underline"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          {tier1.length > 0 && (
            <div className="space-y-2">
              <TierHeading tier={1} count={tier1.length} />
              {tier1.map(agent => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onSelect={handleSelect}
                  selectedAegNodeId={selectedAegNodeId}
                  isSelected={selectedId === agent.id}
                />
              ))}
            </div>
          )}
          {tier2.length > 0 && (
            <div className="space-y-2">
              <TierHeading tier={2} count={tier2.length} />
              {tier2.map(agent => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onSelect={handleSelect}
                  selectedAegNodeId={selectedAegNodeId}
                  isSelected={selectedId === agent.id}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
