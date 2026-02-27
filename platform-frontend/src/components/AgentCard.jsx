const STATE_STYLES = {
  PENDING: 'bg-ink/5 text-ink/70 border-ink/10',
  RUNNING: 'bg-ember/10 text-ember border-ember/30',
  COMPLETED: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  FAILED: 'bg-rose-100 text-rose-700 border-rose-200',
}

export default function AgentCard({ name, state, progress }) {
  const style = STATE_STYLES[state] || STATE_STYLES.PENDING

  return (
    <div className={`rounded-xl border px-3 py-2 text-sm ${style}`}>
      <div className="flex items-center justify-between">
        <span className="font-semibold">{name}</span>
        <span className="mono text-[10px] uppercase tracking-[0.2em]">
          {state}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/60">
        <div
          className="h-full rounded-full bg-current transition-all"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  )
}
