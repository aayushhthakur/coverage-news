import { LayersIcon, RefreshIcon } from './Icons'

export function EmptyState({ title, body, onRetry }) {
  return (
    <div className="flex flex-col items-center px-6 py-16 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-ink-3" aria-hidden="true">
        <LayersIcon />
      </div>
      <h2 className="text-[18px] font-semibold">{title}</h2>
      <p className="mt-1 max-w-[320px] text-[16px] text-ink-2">{body}</p>
      {onRetry && <RetryButton onClick={onRetry} label="Check again" />}
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  const offline = typeof navigator !== 'undefined' && !navigator.onLine
  return (
    <div role="alert" className="flex flex-col items-center px-6 py-16 text-center">
      <h2 className="text-[18px] font-semibold">
        {offline ? "You're offline" : error?.status === 404 ? 'Not found' : "Couldn't load the news"}
      </h2>
      <p className="mt-1 max-w-[320px] text-[16px] text-ink-2">
        {offline ? 'Connect to the internet and try again.'
          : error?.status === 404 ? 'This may have dropped out of the last 48 hours of coverage.'
          : `${error?.message ?? 'Something went wrong'}. Check that the API is running.`}
      </p>
      <RetryButton onClick={onRetry} label="Try again" />
    </div>
  )
}

export function StaleBanner({ onRetry }) {
  return (
    <div role="status" className="mb-3 flex items-center justify-between gap-3 rounded-xl bg-surface-2 px-3 py-1 text-[14px]">
      <span>Showing saved results. Couldn't refresh.</span>
      <button type="button" onClick={onRetry} className="min-h-[44px] font-semibold text-accent">Retry</button>
    </div>
  )
}

function RetryButton({ onClick, label }) {
  return (
    <button type="button" onClick={onClick}
      className="mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-full bg-accent px-5 text-[16px] font-semibold text-accent-ink">
      <RefreshIcon width={18} height={18} /> {label}
    </button>
  )
}
