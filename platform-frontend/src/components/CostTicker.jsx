export default function CostTicker({ tokens, cost }) {
  return (
    <div className="rounded-full border border-ink/10 bg-white/70 px-4 py-2 text-sm shadow-sm">
      <div className="mono text-[10px] uppercase tracking-[0.3em] text-ink/50">
        Live Cost
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-lg font-semibold">${cost.toFixed(3)}</span>
        <span className="text-xs text-ink/50">{tokens} tokens</span>
      </div>
    </div>
  )
}
