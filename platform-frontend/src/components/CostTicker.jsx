import { useEffect, useState, useRef } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export default function CostTicker({ projectId }) {
  const [displayCost, setDisplayCost] = useState(0)
  const [displayTokens, setDisplayTokens] = useState(0)
  const [targetCost, setTargetCost] = useState(0)
  const [targetTokens, setTargetTokens] = useState(0)
  const pollRef = useRef(null)

  // Poll the live ticker endpoint every 3s
  useEffect(() => {
    if (!projectId) return

    const fetchTicker = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/cost/ticker?project_id=${projectId}`)
        if (!res.ok) return
        const data = await res.json()
        setTargetCost(data.total_cost_usd ?? 0)
        setTargetTokens(data.total_tokens ?? 0)
      } catch (e) {
        // silently fail — ticker is non-critical
      }
    }

    fetchTicker()
    pollRef.current = setInterval(fetchTicker, 3000)
    return () => clearInterval(pollRef.current)
  }, [projectId])

  // Smooth animation toward target values
  useEffect(() => {
    const costInterval = setInterval(() => {
      setDisplayCost(prev => {
        const diff = targetCost - prev
        if (Math.abs(diff) < 0.0001) return targetCost
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

  return (
    <div className="relative rounded-lg border border-primary/30 bg-card px-3 py-1.5 text-[11px] shadow-glow-sm">
      <div className="absolute inset-0 rounded-lg bg-gradient-to-r from-transparent via-primary/10 to-transparent" />
      <div className="relative">
        <div className="mono text-[7px] uppercase tracking-[0.2em] text-foreground/50">
          Live Cost
        </div>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className="text-gradient-ember text-lg font-bold">
            ${displayCost.toFixed(3)}
          </span>
          <span className="mono text-[10px] text-foreground/50">
            {Math.round(displayTokens)} tok
          </span>
        </div>
      </div>
    </div>
  )
}