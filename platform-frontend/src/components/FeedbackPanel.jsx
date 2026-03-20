export default function FeedbackPanel() {
  return (
    <div className="workshop-panel rounded-xl p-4">
      <h2 className="mono text-sm font-semibold uppercase tracking-wide text-foreground/70">
        Feedback
      </h2>
      <textarea
        placeholder="Request changes, priorities, or new constraints..."
        className="mt-3 min-h-[120px] w-full rounded-lg border border-border bg-secondary/60 p-3 text-sm text-foreground outline-none focus:border-primary"
      />
      <button className="btn-ember mt-3 w-full rounded-lg px-4 py-2 text-sm font-semibold">
        Send to Director
      </button>
    </div>
  )
}
