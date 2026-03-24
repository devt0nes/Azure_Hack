export default function LogStream({ logs }) {
  return (
    <div className="workshop-panel rounded-xl p-4">
      <h2 className="mono text-sm font-semibold uppercase tracking-wide text-foreground/80">
        Live Logs
      </h2>
      <div className="mono mt-4 max-h-48 space-y-1.5 overflow-y-auto text-xs text-foreground/70">
        {logs.map((log, index) => (
          <p
            key={index}
            className="animate-fade-in rounded-md border border-border bg-secondary/60 px-2.5 py-1.5 transition-all duration-300 hover:bg-secondary"
          >
            <span className="text-primary font-bold">›</span>
            <span className="ml-2 text-foreground/80">{log}</span>
          </p>
        ))}
      </div>
    </div>
  )
}
