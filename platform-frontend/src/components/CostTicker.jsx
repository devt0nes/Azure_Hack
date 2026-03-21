/**
 * CostTicker.jsx — updated to poll real backend data
 * ---------------------------------------------------
 * Keeps the existing animated counter aesthetic exactly as-is.
 * Adds: real data polling from /api/cost/ticker every 3s,
 *       a budget % ring that fills as spend approaches cap,
 *       and an alert dot when a warning/critical alert has fired.
 *
 * Props (all optional — falls back to prop-driven mode if no projectId):
 *   projectId  string   — if provided, polls /api/cost/ticker live
 *   tokens     number   — fallback prop (used by App.jsx SignalR path)
 *   cost       number   — fallback prop
 */

import { useEffect, useState, useRef } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export default function CostTicker({ tokens = 0, cost = 0, projectId }) {
  const [displayCost,   setDisplayCost]   = useState(0)
  const [displayTokens, setDisplayTokens] = useState(0)
  const [liveData,      setLiveData]      = useState(null)   // from /api/cost/ticker
  const pollRef = useRef(null)

  // ── Poll live ticker if we have a projectId ───────────────────────────────
  useEffect(() => {
    if (!projectId) return

    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/cost/ticker?project_id=${projectId}`)
        if (res.ok) {
          const data = await res.json()
          setLiveData(data)
        }
      } catch {
        // silently ignore — fall back to prop values
      }
    }

    poll()
    pollRef.current = setInterval(poll, 3000)
    return () => clearInterval(pollRef.current)
  }, [projectId])

  // Use live data if available, otherwise use props from App.jsx
  const targetCost   = liveData ? liveData.total_cost_usd : cost
  const targetTokens = liveData ? liveData.total_tokens   : tokens
  const budgetUsd    = liveData?.budget_usd    ?? 0
  const pctUsed      = liveData?.pct_budget_used ?? 0
  const capReached   = liveData?.cap_reached   ?? false
  const hasAlert     = liveData?.latest_alert  != null

  // ── Animated counter (unchanged from original) ────────────────────────────
  useEffect(() => {
    const costInterval = setInterval(() => {
      setDisplayCost(prev => {
        const diff = targetCost - prev
        if (Math.abs(diff) < 0.001) return targetCost
        return prev + diff * 0.1
      })
    }, 100)

    const tokenInterval = setInterval(() => {
      setDisplayTokens(prev => {
        if (prev === targetTokens) return targetTokens
        const diff = targetTokens - prev
        if (Math.abs(diff) < 1) return targetTokens
        return prev + Math.sign(diff) * Math.ceil(Math.abs(diff) * 0.15)
      })
    }, 150)

    return () => {
      clearInterval(costInterval)
      clearInterval(tokenInterval)
    }
  }, [targetCost, targetTokens])

  // ── Budget ring colour ────────────────────────────────────────────────────
  const ringColor =
    capReached      ? '#ef4444' :
    pctUsed >= 90   ? '#f97316' :
    pctUsed >= 75   ? '#eab308' :
                      '#f26a2e'

  const circumference = 2 * Math.PI * 20
  const ringOffset    = circumference * (1 - Math.min(pctUsed, 100) / 100)

  return (
    <div className="relative rounded-full border border-ember/30 bg-gradient-to-r from-ember/5 via-amber-500/5 to-orange-500/5 px-6 py-3 text-sm backdrop-blur-xs shadow-glow-sm">
      <div className="absolute inset-0 rounded-full bg-gradient-to-r from-transparent via-white/10 to-transparent" />

      {/* Alert dot */}
      {hasAlert && !capReached && (
        <span className="absolute -right-1 -top-1 flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-amber-500" />
        </span>
      )}
      {capReached && (
        <span className="absolute -right-1 -top-1 flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-red-500" />
        </span>
      )}

      <div className="relative flex items-center gap-3">
        {/* Budget ring — only shown when we have live data */}
        {liveData && budgetUsd > 0 && (
          <div className="relative h-11 w-11 flex-shrink-0">
            <svg className="h-full w-full -rotate-90" viewBox="0 0 44 44">
              <circle cx="22" cy="22" r="20" fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth="3" />
              <circle
                cx="22" cy="22" r="20"
                fill="none"
                stroke={ringColor}
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={ringOffset}
                style={{ transition: 'stroke-dashoffset 0.6s ease, stroke 0.3s ease' }}
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="mono text-[9px] font-black" style={{ color: ringColor }}>
                {Math.round(pctUsed)}%
              </span>
            </div>
          </div>
        )}

        {/* Cost + tokens */}
        <div>
          <div className="mono text-[9px] uppercase tracking-[0.3em] text-ink/60">
            {liveData ? 'Live Cost' : 'Cost'}
          </div>
          <div className="mt-1 flex items-baseline gap-3">
            <span className="bg-gradient-to-r from-ember via-orange-400 to-amber-400 bg-clip-text text-2xl font-bold text-transparent">
              ${displayCost.toFixed(3)}
            </span>
            <span className="mono text-xs text-ink/50">{Math.round(displayTokens)} tokens</span>
          </div>
          {liveData && budgetUsd > 0 && (
            <div className="mono text-[9px] text-ink/30 mt-0.5">
              of ${budgetUsd.toFixed(2)} budget
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
