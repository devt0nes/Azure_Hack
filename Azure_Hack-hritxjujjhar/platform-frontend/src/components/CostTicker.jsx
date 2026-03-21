import { useEffect, useState } from 'react'

export default function CostTicker({ tokens, cost }) {
  const [displayCost, setDisplayCost] = useState(0)
  const [displayTokens, setDisplayTokens] = useState(0)

  useEffect(() => {
    const costInterval = setInterval(() => {
      setDisplayCost((prev) => {
        const diff = cost - prev
        if (Math.abs(diff) < 0.001) return cost
        return prev + diff * 0.1
      })
    }, 100)

    const tokenInterval = setInterval(() => {
      setDisplayTokens((prev) => {
        if (prev === tokens) return tokens
        const diff = tokens - prev
        if (Math.abs(diff) < 1) return tokens
        return prev + Math.sign(diff) * Math.ceil(Math.abs(diff) * 0.15)
      })
    }, 150)

    return () => {
      clearInterval(costInterval)
      clearInterval(tokenInterval)
    }
  }, [cost, tokens])

  return (
    <div className="relative rounded-xl border border-primary/30 bg-card px-6 py-3 text-sm shadow-glow-sm">
      <div className="absolute inset-0 rounded-xl bg-gradient-to-r from-transparent via-primary/10 to-transparent" />
      <div className="relative">
        <div className="mono text-[9px] uppercase tracking-[0.3em] text-foreground/50">
          Live Cost
        </div>
        <div className="mt-2 flex items-baseline gap-3">
          <span className="text-gradient-ember text-2xl font-bold">
            ${displayCost.toFixed(3)}
          </span>
          <span className="mono text-xs text-foreground/50">{Math.round(displayTokens)} tokens</span>
        </div>
      </div>
    </div>
  )
}
