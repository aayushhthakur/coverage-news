// Unsplash photos are hotlinked and sized via URL params on urls.raw.
// They are illustrative (chosen by topic), so they are hidden from screen readers.

const sized = (raw, w, ratio) => `${raw}&w=${w}&h=${Math.round(w / ratio)}&fit=crop&auto=format&q=70`

function Picture({ image, ratio, eager, className = '' }) {
  return (
    <img
      src={sized(image.raw, 800, ratio)}
      srcSet={[400, 800, 1200].map((w) => `${sized(image.raw, w, ratio)} ${w}w`).join(', ')}
      sizes="(min-width: 480px) 448px, calc(100vw - 32px)"
      alt=""
      aria-hidden="true"
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      className={`block h-full w-full object-cover ${className}`}
    />
  )
}

const linkCls = 'inline-flex min-h-[44px] items-center underline-offset-2 hover:underline focus-visible:underline'
const inlineLinkCls = 'py-[14px] text-ink-2 underline decoration-line underline-offset-2'

/** Full-bleed image at the top of a card, with the credit over its bottom edge. */
export function CardImage({ image, eager }) {
  const { credit } = image
  return (
    <div className="relative w-full overflow-hidden" style={{ aspectRatio: '2.4 / 1', background: image.color ?? 'var(--surface-2)' }}>
      <Picture image={image} ratio={2.4} eager={eager} />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-black/55 to-transparent" />
      <p className="absolute bottom-0 right-0 z-10 flex items-center gap-1 px-3 text-[12px] font-medium text-white [text-shadow:0_1px_2px_rgba(0,0,0,.6)]">
        <span aria-hidden="true">Photo:</span>
        <a href={credit.profile_url} target="_blank" rel="noopener noreferrer" className={linkCls}
          aria-label={`Photo by ${credit.name} (opens Unsplash)`}>
          <span className="max-w-[150px] truncate">{credit.name}</span>
        </a>
        <span aria-hidden="true">/</span>
        <a href={credit.unsplash_url} target="_blank" rel="noopener noreferrer" className={linkCls}>Unsplash</a>
      </p>
    </div>
  )
}

/** Hero image on the event/story screen, with a plain-text credit line under it. */
export function HeroImage({ image }) {
  const { credit } = image
  return (
    <figure className="mb-4">
      <div className="overflow-hidden rounded-xl" style={{ aspectRatio: '2 / 1', background: image.color ?? 'var(--surface-2)' }}>
        <Picture image={image} ratio={2} eager />
      </div>
      {/* inline links with vertical padding: 44px tap height without changing line height */}
      <figcaption className="mt-2 text-[14px] leading-[22px] text-ink-3">
        Illustrative photo by{' '}
        <a href={credit.profile_url} target="_blank" rel="noopener noreferrer" className={inlineLinkCls}>{credit.name}</a>
        {' '}on{' '}
        <a href={credit.unsplash_url} target="_blank" rel="noopener noreferrer" className={inlineLinkCls}>Unsplash</a>
      </figcaption>
    </figure>
  )
}
