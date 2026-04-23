import { isRouteErrorResponse, Link, useRevalidator, useRouteError } from 'react-router-dom'

function formatError(error: unknown): string {
  if (isRouteErrorResponse(error)) {
    return error.statusText || `${error.status}`
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Unknown error'
}

export function RouteError() {
  const error = useRouteError()
  const { revalidate } = useRevalidator()
  const message = formatError(error)
  const looksNetwork =
    (error instanceof TypeError && /fetch|network|load failed/i.test(error.message)) ||
    /did not become ready|Failed to fetch|Request failed|ECONNREFUSED/i.test(message)

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center text-slate-200">
      <h1 className="font-mono text-sm font-bold uppercase tracking-widest text-rose-300">Could not load this page</h1>
      <p className="max-w-lg text-sm text-slate-400">
        {looksNetwork
          ? 'The app could not reach the API. On first launch, the packed sidecar can take 1–2 minutes to start (PyInstaller extract). In the browser, run the API (e.g. uvicorn) or set VITE_API_BASE_URL. If the desktop app fails to start at all, rebuild the sidecar with desktop/scripts/build-sidecar.ps1.'
          : 'An error happened while loading data for this route.'}
      </p>
      <pre className="max-w-full overflow-x-auto rounded-lg border border-white/10 bg-black/30 px-4 py-3 text-left font-mono text-xs text-rose-200/90">
        {message}
      </pre>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => revalidate()}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-500"
        >
          Try again
        </button>
        <Link
          to="/"
          className="rounded-md border border-white/15 px-4 py-2 text-sm text-slate-200 transition hover:border-white/30"
        >
          Back to dashboard
        </Link>
      </div>
    </div>
  )
}
