export function RouteLoadingFallback({ message = 'Loading…' }: { message?: string }) {
  return (
    <div
      className="flex min-h-[50vh] flex-col items-center justify-center gap-3 px-6"
      role="status"
      aria-live="polite"
    >
      <div
        className="h-9 w-9 animate-spin rounded-full border-2 border-emerald-500/30 border-t-emerald-400"
        aria-hidden
      />
      <p className="font-mono text-xs uppercase tracking-widest text-slate-500">{message}</p>
    </div>
  )
}
