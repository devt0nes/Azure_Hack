export default function LogStream({ logs }) {
  return (
    <div className="rounded-2xl border border-ink/10 bg-gradient-to-br from-sand/50 via-white/70 to-haze/40 p-4 backdrop-blur-xs shadow-glass">
      <h2 className="text-sm font-semibold uppercase tracking-wide bg-gradient-to-r from-ink to-ink/70 bg-clip-text text-transparent">
        Live Logs
      </h2>
      <div className="mono mt-4 max-h-48 space-y-1.5 overflow-y-auto text-xs text-ink/70">
        {logs.map((log, index) => (
          <p
            key={index}
            className="animate-fade-in rounded-lg bg-white/30 px-2.5 py-1.5 backdrop-blur-xs border border-white/20 hover:bg-white/50 transition-all duration-300"
          >
            <span className="text-ember font-bold">›</span>
            <span className="ml-2 text-ink/80">{log}</span>
          </p>
        ))}
      </div>
    </div>
  )
}
