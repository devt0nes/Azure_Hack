const STATE_STYLES = {
  PENDING: {
    bg: 'bg-gradient-to-br from-slate-500/10 via-slate-500/5 to-slate-500/0',
    border: 'border-slate-400/20',
    text: 'text-ink/70',
    progress: 'bg-gradient-to-r from-slate-400 to-slate-500',
    glow: '',
  },
  RUNNING: {
    bg: 'bg-gradient-to-br from-ember/20 via-ember/10 to-ember/5',
    border: 'border-ember/40 shadow-glow-sm',
    text: 'text-ember',
    progress: 'bg-gradient-to-r from-ember via-orange-400 to-ember',
    glow: 'shadow-glow-sm',
  },
  COMPLETED: {
    bg: 'bg-gradient-to-br from-emerald-100/60 via-emerald-50/40 to-emerald-100/20',
    border: 'border-emerald-300/40',
    text: 'text-emerald-700',
    progress: 'bg-gradient-to-r from-emerald-400 to-emerald-500',
    glow: '',
  },
  FAILED: {
    bg: 'bg-gradient-to-br from-rose-100/60 via-rose-50/40 to-rose-100/20',
    border: 'border-rose-300/40',
    text: 'text-rose-700',
    progress: 'bg-gradient-to-r from-rose-400 to-rose-500',
    glow: '',
  },
}

export default function AgentCard({ name, state, progress }) {
  const styles = STATE_STYLES[state] || STATE_STYLES.PENDING

  return (
    <div
      className={`group relative rounded-2xl border px-4 py-3 text-sm backdrop-blur-xs transition-all duration-300 hover:scale-105 hover:shadow-glass ${styles.bg} ${styles.border} ${styles.glow}`}
    >
      <div className="absolute inset-0 rounded-2xl bg-gradient-to-r from-white/0 via-white/5 to-white/0 opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="relative flex items-center justify-between">
        <span className="font-semibold">{name}</span>
        <span className="mono text-[10px] uppercase tracking-[0.2em] opacity-75">
          {state}
        </span>
      </div>
      <div className="relative mt-3 h-2.5 overflow-hidden rounded-full bg-white/40 backdrop-blur-xs">
        <div
          className={`h-full rounded-full ${styles.progress} shadow-lg transition-all duration-700 ease-out`}
          style={{ width: `${progress}%` }}
        />
        {progress > 0 && progress < 100 && (
          <div className="absolute inset-0 animate-shimmer bg-gradient-to-r from-transparent via-white/40 to-transparent" />
        )}
      </div>
      <div className="mt-2 flex items-center justify-between text-xs opacity-60">
        <span>{progress}%</span>
        <span>{progress === 100 ? 'Done' : progress > 0 ? 'In Progress' : 'Waiting'}</span>
      </div>
    </div>
  )
}
