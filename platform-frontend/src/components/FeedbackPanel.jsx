export default function FeedbackPanel() {
  return (
    <div className="rounded-2xl border border-ink/10 bg-white/70 p-4 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/60">
        Feedback
      </h2>
      <textarea
        placeholder="Request changes, priorities, or new constraints..."
        className="mt-3 min-h-[120px] w-full rounded-xl border border-ink/10 bg-white/90 p-3 text-sm outline-none focus:border-ember"
      />
      <button className="mt-3 w-full rounded-full bg-ember px-4 py-2 text-sm font-semibold text-white hover:bg-ember/90">
        Send to Director
      </button>
    </div>
  )
}
