export default function LogStream({ logs }) {
  return (
    <div className="workshop-panel flex h-full min-h-0 flex-col rounded-xl p-4">
      <div className="mono min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1 text-xs text-foreground/70">
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