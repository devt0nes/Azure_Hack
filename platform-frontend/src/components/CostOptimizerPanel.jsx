/**
 * CostOptimizerPanel.jsx
 * ----------------------
 * Full Budget Cape dashboard panel — shown in the left sidebar popup system.
 * Matches existing App.jsx design tokens: ember / orange-400 / ink / midnight / sand / haze
 *
 * Sections:
 *  1. Live spend gauge  — circular arc showing % of budget used
 *  2. Budget setter     — inline input to update the cap
 *  3. Tier breakdown    — token/cost per model (Phi-4 / GPT-4o-mini / GPT-4o / o1)
 *  4. Agent breakdown   — per-agent spend bars
 *  5. Usage log         — last 20 model calls with escalation markers
 *  6. Alerts banner     — warning / critical / cap_reached
 *  7. Escalation log    — what was upgraded and why
 */

import { useState, useEffect, useCallback, useRef } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

// ─── API helpers ─────────────────────────────────────────────────────────────
async function fetchJSON(url) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 8000)
  let res
  try {
    res = await fetch(url, { signal: controller.signal })
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('Request timed out')
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// ─── Tier colours ─────────────────────────────────────────────────────────────
const TIER_META = {
  simple:         { label: 'Phi-4',            color: '#38bdf8', bg: 'bg-sky-100',    text: 'text-sky-700'    },
  intermediate:   { label: 'GPT-4o-mini',      color: '#a78bfa', bg: 'bg-violet-100', text: 'text-violet-700' },
  complex:        { label: 'GPT-4o',           color: '#f26a2e', bg: 'bg-ember/10',   text: 'text-ember'      },
  'high-reasoning':{ label: 'GPT-4o + o1',     color: '#fb923c', bg: 'bg-orange-100', text: 'text-orange-700' },
}

function tierMeta(tier) {
  return TIER_META[tier] || { label: tier, color: '#94a3b8', bg: 'bg-ink/10', text: 'text-ink/60' }
}

// ─── Circular spend gauge ─────────────────────────────────────────────────────
function SpendGauge({ pct, spendUsd, budgetUsd, capReached }) {
  const clampedPct = Math.min(pct, 100)
  const radius = 52
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - clampedPct / 100)

  const strokeColor =
    capReached        ? '#ef4444' :
    clampedPct >= 90  ? '#f97316' :
    clampedPct >= 75  ? '#eab308' :
                        '#f26a2e'

  return (
    <div className="flex flex-col items-center py-4">
      <div className="relative h-36 w-36">
        <svg className="h-full w-full -rotate-90" viewBox="0 0 120 120">
          {/* Track */}
          <circle cx="60" cy="60" r={radius} fill="none" stroke="rgba(0,0,0,0.06)" strokeWidth="10" />
          {/* Progress */}
          <circle
            cx="60" cy="60" r={radius}
            fill="none"
            stroke={strokeColor}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{ transition: 'stroke-dashoffset 0.6s ease, stroke 0.4s ease' }}
          />
        </svg>
        {/* Center text */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="mono text-2xl font-black text-midnight">{clampedPct.toFixed(0)}%</span>
          <span className="text-[10px] font-semibold uppercase tracking-widest text-ink/40">used</span>
        </div>
      </div>
      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="mono text-xl font-bold text-midnight">${spendUsd.toFixed(4)}</span>
        <span className="text-xs text-ink/40">/ ${budgetUsd.toFixed(2)}</span>
      </div>
      {capReached && (
        <span className="mt-2 rounded-full bg-red-100 border border-red-200 px-3 py-0.5 text-[11px] font-bold text-red-600">
          ● CAP REACHED — non-critical agents paused
        </span>
      )}
    </div>
  )
}

// ─── Budget setter ────────────────────────────────────────────────────────────
function BudgetSetter({ currentBudget, projectId, onUpdated }) {
  const [value,   setValue]   = useState(currentBudget.toFixed(2))
  const [saving,  setSaving]  = useState(false)
  const [msg,     setMsg]     = useState(null)

  const handleSave = async () => {
    const num = parseFloat(value)
    if (isNaN(num) || num <= 0) { setMsg({ type: 'err', text: 'Enter a positive number' }); return }
    setSaving(true)
    try {
      await postJSON(`${API_BASE}/api/cost/budget?project_id=${projectId}`, { budget_usd: num })
      setMsg({ type: 'ok', text: 'Budget updated ✓' })
      onUpdated(num)
      setTimeout(() => setMsg(null), 2500)
    } catch (e) {
      setMsg({ type: 'err', text: e.message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-2xl border border-white/50 bg-white/60 p-4">
      <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-ink/40">Budget Cap (USD)</p>
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-ink/50">$</span>
        <input
          type="number"
          min="0.01"
          step="0.5"
          value={value}
          onChange={e => setValue(e.target.value)}
          className="mono w-24 rounded-xl border border-white/50 bg-white/80 px-3 py-1.5 text-sm font-bold text-midnight outline-none focus:border-ember/30 focus:ring-1 focus:ring-ember/20"
        />
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded-xl bg-gradient-to-r from-ember to-orange-400 px-4 py-1.5 text-xs font-bold text-white shadow-sm hover:opacity-90 disabled:opacity-50 transition"
        >
          {saving ? 'Saving…' : 'Update'}
        </button>
      </div>
      {msg && (
        <p className={`mt-1.5 text-[11px] font-medium ${msg.type === 'ok' ? 'text-emerald-600' : 'text-red-500'}`}>
          {msg.text}
        </p>
      )}
    </div>
  )
}

// ─── Tier breakdown bar ───────────────────────────────────────────────────────
function TierBar({ tier, data, maxCost }) {
  const meta   = tierMeta(tier)
  const widthPct = maxCost > 0 ? (data.cost_usd / maxCost) * 100 : 0
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className={`rounded-full border px-2 py-0.5 font-semibold ${meta.bg} ${meta.text} border-current/20`}>
          {meta.label}
        </span>
        <div className="flex items-center gap-3 text-ink/60">
          <span className="mono">{data.calls} call{data.calls !== 1 ? 's' : ''}</span>
          <span className="mono">{data.tokens.toLocaleString()} tok</span>
          <span className="mono font-bold text-midnight">${data.cost_usd.toFixed(5)}</span>
        </div>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink/8">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${widthPct}%`, backgroundColor: meta.color }}
        />
      </div>
    </div>
  )
}

// ─── Agent spend row ──────────────────────────────────────────────────────────
function AgentRow({ agent, maxCost }) {
  const widthPct = maxCost > 0 ? (agent.cost_usd / maxCost) * 100 : 0
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        <div className="min-w-0">
          <span className="mono font-semibold text-midnight truncate block max-w-[160px]" title={agent.agent_id}>
            {agent.agent_role.replace(/_/g, ' ')}
          </span>
        </div>
        <div className="flex items-center gap-3 text-ink/60 flex-shrink-0">
          <span className="mono">{agent.tokens.toLocaleString()} tok</span>
          {agent.escalations > 0 && (
            <span className="rounded-full bg-orange-100 border border-orange-200 px-1.5 py-0.5 text-[10px] font-bold text-orange-600">
              ↑{agent.escalations}
            </span>
          )}
          <span className="mono font-bold text-midnight">${agent.cost_usd.toFixed(5)}</span>
        </div>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-ink/8">
        <div
          className="h-full rounded-full bg-gradient-to-r from-ember to-orange-400 transition-all duration-700"
          style={{ width: `${widthPct}%` }}
        />
      </div>
    </div>
  )
}

// ─── Usage log row ────────────────────────────────────────────────────────────
function UsageRow({ record }) {
  const meta = tierMeta(record.model_tier)
  return (
    <div className="flex items-start gap-2 border-b border-ink/5 py-2 last:border-0">
      <div className="mt-0.5 flex-shrink-0">
        <span className={`inline-block rounded-md border px-1.5 py-0.5 text-[9px] font-bold ${meta.bg} ${meta.text} border-current/20`}>
          {meta.label}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[11px] font-medium text-midnight" title={record.task_description}>
          {record.task_description}
        </p>
        <p className="text-[10px] text-ink/40">{record.agent_role.replace(/_/g, ' ')}</p>
      </div>
      <div className="flex-shrink-0 text-right">
        <p className="mono text-[11px] font-bold text-midnight">${record.cost_usd.toFixed(5)}</p>
        <p className="mono text-[10px] text-ink/40">{record.total_tokens} tok</p>
        {record.escalated_from && (
          <p className="text-[10px] font-semibold text-orange-500">↑ from {record.escalated_from}</p>
        )}
      </div>
    </div>
  )
}

// ─── Alert banner ─────────────────────────────────────────────────────────────
function AlertBanner({ alert }) {
  const styles = {
    warning:    'border-yellow-300 bg-yellow-50 text-yellow-800',
    critical:   'border-orange-300 bg-orange-50 text-orange-800',
    cap_reached:'border-red-300   bg-red-50   text-red-800',
  }
  const icons = { warning: '⚠️', critical: '🔶', cap_reached: '🔴' }
  return (
    <div className={`flex items-start gap-2 rounded-xl border px-3 py-2 text-xs ${styles[alert.alert_type] || styles.warning}`}>
      <span>{icons[alert.alert_type] || '⚠️'}</span>
      <div>
        <p className="font-semibold">{alert.message}</p>
        <p className="mt-0.5 opacity-60 text-[10px]">{new Date(alert.timestamp).toLocaleTimeString()}</p>
      </div>
    </div>
  )
}

// ─── Escalation row ───────────────────────────────────────────────────────────
function EscalationRow({ esc }) {
  const from = tierMeta(esc.original_tier)
  const to   = tierMeta(esc.escalated_to)
  return (
    <div className="flex items-center gap-2 border-b border-ink/5 py-2 last:border-0 text-[11px]">
      <span className={`rounded-md border px-1.5 py-0.5 font-semibold ${from.bg} ${from.text} border-current/20`}>{from.label}</span>
      <span className="text-ink/30">→</span>
      <span className={`rounded-md border px-1.5 py-0.5 font-semibold ${to.bg} ${to.text} border-current/20`}>{to.label}</span>
      <span className="flex-1 truncate text-ink/50 ml-1" title={esc.task_class}>{esc.task_class}</span>
      <span className="flex-shrink-0 text-ink/30">{esc.agent_role.replace(/_/g, ' ')}</span>
    </div>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────
function Section({ title, count, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-2xl border border-white/50 bg-white/60 overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex w-full items-center justify-between px-4 py-3"
      >
        <span className="text-[10px] font-black uppercase tracking-widest text-ink/50">
          {title}
          {count !== undefined && (
            <span className="ml-2 rounded-full bg-ink/8 px-1.5 py-0.5 text-[10px] font-semibold">{count}</span>
          )}
        </span>
        <svg
          className={`h-3.5 w-3.5 text-ink/30 transition-transform ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
        >
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>
      {open && <div className="px-4 pb-4 space-y-2">{children}</div>}
    </div>
  )
}

// ─── Empty state ──────────────────────────────────────────────────────────────
function EmptyState({ message }) {
  return (
    <p className="py-3 text-center text-[11px] text-ink/30 font-medium">{message}</p>
  )
}

// ─── Main panel ───────────────────────────────────────────────────────────────
export default function CostOptimizerPanel({ projectId }) {
  const [summary,     setSummary]     = useState(null)
  const [usage,       setUsage]       = useState([])
  const [escalations, setEscalations] = useState([])
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)
  const [activeTab,   setActiveTab]   = useState('overview')  // 'overview' | 'usage' | 'escalations'
  const tickerIntervalRef = useRef(null)
  const detailsIntervalRef = useRef(null)

  const loadTicker = useCallback(async () => {
    if (!projectId) return null
    const ticker = await fetchJSON(`${API_BASE}/api/cost/ticker?project_id=${projectId}`)

    // Only update if the optimizer has actual data — ignore freshly created empty ones.
    // An empty optimizer has total_cost_usd=0 AND total_tokens=0 AND no alerts.
    // We still update if we previously had data (so a real zero is shown after a reset).
    const hasRealData = (
      (ticker.total_cost_usd ?? 0) > 0 ||
      (ticker.total_tokens ?? 0) > 0 ||
      ticker.latest_alert != null
    )

    setSummary(prev => {
      const hadDataBefore = prev && (
        (prev.total_cost_usd ?? 0) > 0 ||
        (prev.total_tokens ?? 0) > 0
      )
      if (!hasRealData && !hadDataBefore) {
        // No data yet — keep loading spinner, don't flash zeros
        return prev
      }
      return {
        project_id: projectId,
        total_tokens: ticker.total_tokens ?? 0,
        total_cost_usd: ticker.total_cost_usd ?? 0,
        budget_usd: ticker.budget_usd ?? 0,
        pct_budget_used: ticker.pct_budget_used ?? 0,
        cap_reached: ticker.cap_reached ?? false,
        total_calls: prev?.total_calls ?? 0,
        total_escalations: prev?.total_escalations ?? 0,
        agent_breakdown: prev?.agent_breakdown || [],
        tier_breakdown: prev?.tier_breakdown || {},
        alerts: ticker.latest_alert ? [ticker.latest_alert] : (prev?.alerts || []),
        learned_overrides: prev?.learned_overrides || {},
        paused_agents: prev?.paused_agents || [],
      }
    })
    setError(null)
    if (hasRealData) setLoading(false)
    return ticker
  }, [projectId])

  const loadDetails = useCallback(async () => {
    if (!projectId) return
    try {
      const results = await Promise.allSettled([
        fetchJSON(`${API_BASE}/api/cost/summary?project_id=${projectId}`),
        fetchJSON(`${API_BASE}/api/cost/usage?project_id=${projectId}&limit=20`),
        fetchJSON(`${API_BASE}/api/cost/escalations?project_id=${projectId}`),
      ])

      const [summaryResult, usageResult, escalationsResult] = results
      const summary = summaryResult.status === 'fulfilled' ? summaryResult.value : null
      const usagePayload = usageResult.status === 'fulfilled' ? usageResult.value : null
      const escalationsPayload = escalationsResult.status === 'fulfilled' ? escalationsResult.value : null

      if (summary) {
        setSummary(summary)
      }
      setUsage(usagePayload?.records || [])
      setEscalations(escalationsPayload?.escalations || [])
      setError(null)
    } catch (e) {
      try {
        await loadTicker()
      } catch {
        setError(e.message)
      }
    } finally {
      setLoading(false)
    }
  }, [projectId, loadTicker])

  const load = useCallback(async () => {
    if (!projectId) return
    await loadTicker()
    await loadDetails()
  }, [projectId, loadTicker, loadDetails])

  // Poll ticker frequently without recreating the interval on each summary update.
  useEffect(() => {
    if (!projectId) return undefined
    loadTicker()
    tickerIntervalRef.current = setInterval(loadTicker, 1000)
    return () => clearInterval(tickerIntervalRef.current)
  }, [projectId, loadTicker])

  // Refresh heavier detail endpoints less often to avoid flicker and request churn.
  useEffect(() => {
    if (!projectId) return undefined
    loadDetails()
    detailsIntervalRef.current = setInterval(loadDetails, 3000)
    return () => clearInterval(detailsIntervalRef.current)
  }, [projectId, loadDetails])

  // ── Loading ──────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <div className="h-8 w-8 rounded-full border-2 border-ember/30 border-t-ember animate-spin" />
        <p className="text-xs font-semibold text-ink/50">Waiting for cost data…</p>
        <p className="text-[11px] text-ink/30 max-w-[220px]">
          Data will appear once a project starts generating code.
        </p>
      </div>
    )
  }

  // ── Error ────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-center">
        <p className="text-sm font-semibold text-red-600">Could not load cost data</p>
        <p className="mt-1 text-xs text-red-500">{error}</p>
      </div>
    )
  }

  if (!summary) return null

  // Derived values
  const tierBreakdown  = summary.tier_breakdown  || {}
  const agentBreakdown = summary.agent_breakdown || []
  const alerts         = summary.alerts          || []
  const maxTierCost    = Math.max(...Object.values(tierBreakdown).map(t => t.cost_usd), 0.000001)
  const maxAgentCost   = Math.max(...agentBreakdown.map(a => a.cost_usd), 0.000001)

  const TABS = [
    { id: 'overview',    label: 'Overview'    },
    { id: 'usage',       label: `Log (${usage.length})` },
    { id: 'escalations', label: `Escalations (${escalations.length})` },
  ]

  return (
    <div className="flex flex-col gap-4">

      {/* ── Tab bar ──────────────────────────────────────────────────────── */}
      <div className="flex gap-1 rounded-xl border border-white/40 bg-white/50 p-1">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 rounded-lg py-1.5 text-[11px] font-semibold transition-all ${
              activeTab === tab.id
                ? 'bg-white shadow-sm text-ember border border-ember/20'
                : 'text-ink/50 hover:text-ink/70'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Alerts ───────────────────────────────────────────────────────── */}
      {alerts.length > 0 && (
        <div className="space-y-2">
          {alerts.map((a, i) => <AlertBanner key={i} alert={a} />)}
        </div>
      )}

      {/* ══════════════════ OVERVIEW TAB ══════════════════════════════════ */}
      {activeTab === 'overview' && (
        <div className="space-y-4">

          {/* Spend gauge */}
          <div className="rounded-2xl border border-white/50 bg-white/60">
            <SpendGauge
              pct={summary.pct_budget_used}
              spendUsd={summary.total_cost_usd}
              budgetUsd={summary.budget_usd}
              capReached={summary.cap_reached}
            />
            {/* Stats row */}
            <div className="grid grid-cols-3 border-t border-ink/8 divide-x divide-ink/8">
              {[
                { label: 'Total Calls',  value: summary.total_calls },
                { label: 'Total Tokens', value: summary.total_tokens.toLocaleString() },
                { label: 'Escalations', value: summary.total_escalations },
              ].map(s => (
                <div key={s.label} className="flex flex-col items-center py-3">
                  <span className="mono text-base font-black text-midnight">{s.value}</span>
                  <span className="text-[10px] text-ink/40 uppercase tracking-wide">{s.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Budget setter */}
          <BudgetSetter
            currentBudget={summary.budget_usd}
            projectId={projectId}
            onUpdated={() => load()}
          />

          {/* Tier breakdown */}
          <Section title="By Model Tier" defaultOpen={true}>
            {Object.keys(tierBreakdown).length === 0
              ? <EmptyState message="No model calls recorded yet" />
              : Object.entries(tierBreakdown).map(([tier, data]) => (
                  <TierBar key={tier} tier={tier} data={data} maxCost={maxTierCost} />
                ))
            }
          </Section>

          {/* Agent breakdown */}
          <Section title="By Agent" count={agentBreakdown.length} defaultOpen={true}>
            {agentBreakdown.length === 0
              ? <EmptyState message="No agents have run yet" />
              : agentBreakdown
                  .sort((a, b) => b.cost_usd - a.cost_usd)
                  .map(agent => (
                    <AgentRow key={agent.agent_id} agent={agent} maxCost={maxAgentCost} />
                  ))
            }
          </Section>

          {/* Learned overrides */}
          {Object.keys(summary.learned_overrides || {}).length > 0 && (
            <Section title="Learned Heuristics" defaultOpen={false}>
              {Object.entries(summary.learned_overrides).map(([task, tier]) => (
                <div key={task} className="flex items-center justify-between text-[11px] py-1 border-b border-ink/5 last:border-0">
                  <span className="truncate text-ink/60 max-w-[200px]" title={task}>{task}</span>
                  <span className={`rounded-md border px-1.5 py-0.5 font-semibold ${tierMeta(tier).bg} ${tierMeta(tier).text} border-current/20`}>
                    {tierMeta(tier).label}
                  </span>
                </div>
              ))}
            </Section>
          )}
        </div>
      )}

      {/* ══════════════════ USAGE LOG TAB ════════════════════════════════ */}
      {activeTab === 'usage' && (
        <div className="rounded-2xl border border-white/50 bg-white/60 px-4 py-3">
          {usage.length === 0
            ? <EmptyState message="No model calls recorded yet" />
            : usage.slice().reverse().map((record, i) => (
                <UsageRow key={i} record={record} />
              ))
          }
        </div>
      )}

      {/* ══════════════════ ESCALATIONS TAB ══════════════════════════════ */}
      {activeTab === 'escalations' && (
        <div className="space-y-3">
          <div className="rounded-2xl border border-white/50 bg-white/60 px-4 py-3">
            {escalations.length === 0
              ? <EmptyState message="No escalations yet — models are routing efficiently" />
              : escalations.slice().reverse().map((esc, i) => (
                  <EscalationRow key={i} esc={esc} />
                ))
            }
          </div>
          {Object.keys(summary.learned_overrides || {}).length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
              <p className="text-[10px] font-black uppercase tracking-widest text-amber-600 mb-2">
                Learned Overrides ({Object.keys(summary.learned_overrides).length})
              </p>
              <p className="text-[11px] text-amber-700">
                These task classes have escalated 3+ times and will now skip to a higher model by default.
              </p>
            </div>
          )}
        </div>
      )}

    </div>
  )
}
