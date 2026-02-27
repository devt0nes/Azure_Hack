export default function LogStream({ logs }) {
  return (
    <div className="rounded-2xl border border-ink/10 bg-white/70 p-4 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/60">
        Live Logs
      </h2>
      <div className="mono mt-3 max-h-48 space-y-2 overflow-y-auto text-xs text-ink/70">
        {logs.map((log, index) => (
          <p key={index}>
            <span className="text-ember">›</span> {log}
          </p>
        ))}
      </div>
    </div>
  )
}
