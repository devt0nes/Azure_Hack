const STATE_STYLES = {
  PENDING: {
    bg: 'bg-card',
    border: 'border-border',
    text: 'text-foreground/70',
    progress: 'bg-gradient-to-r from-muted-foreground/50 to-muted-foreground/70',
    glow: '',
  },
  RUNNING: {
    bg: 'bg-card',
    border: 'border-primary/40 shadow-glow-sm',
    text: 'text-primary',
    progress: 'bg-gradient-to-r from-primary via-orange-400 to-primary',
    glow: 'shadow-glow-sm',
  },
  COMPLETED: {
    bg: 'bg-card',
    border: 'border-emerald-500/40',
    text: 'text-emerald-400',
    progress: 'bg-gradient-to-r from-emerald-400 to-emerald-500',
    glow: '',
  },
  FAILED: {
    bg: 'bg-card',
    border: 'border-rose-500/40',
    text: 'text-rose-400',
    progress: 'bg-gradient-to-r from-rose-400 to-rose-500',
    glow: '',
  },
}

export default function AgentCard({ name, state, progress }) {
  const styles = STATE_STYLES[state] || STATE_STYLES.PENDING

  return (
    <div
      className={`group relative rounded-xl border px-4 py-3 text-sm transition-all duration-300 hover:border-foreground/20 ${styles.bg} ${styles.border} ${styles.glow}`}
    >
      <div className="absolute inset-0 rounded-xl bg-gradient-to-r from-transparent via-primary/5 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="relative flex items-center justify-between">
        <span className="mono text-[11px] font-semibold text-foreground">{name}</span>
        <span className="mono text-[10px] uppercase tracking-[0.2em] text-foreground/60">
          {state}
        </span>
      </div>
      <div className="relative mt-3 h-2 overflow-hidden rounded-full bg-secondary">
        <div
          className={`h-full rounded-full ${styles.progress} shadow-lg transition-all duration-700 ease-out`}
          style={{ width: `${progress}%` }}
        />
        {progress > 0 && progress < 100 && (
          <div className="absolute inset-0 animate-shimmer bg-gradient-to-r from-transparent via-white/20 to-transparent" />
        )}
      </div>
      <div className={`mt-2 flex items-center justify-between text-xs ${styles.text}`}>
        <span>{progress}%</span>
        <span>{progress === 100 ? 'Done' : progress > 0 ? 'In Progress' : 'Waiting'}</span>
      </div>
    </div>
  )
}
