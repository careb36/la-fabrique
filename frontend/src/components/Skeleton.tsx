/**
 * Reusable skeleton loader components using the design system `.skeleton` class.
 * Usage:
 *   <SkeletonLine />                  — full-width single line
 *   <SkeletonLine width="w-2/3" />    — partial-width line
 *   <SkeletonBlock height="h-32" />   — block (card, image, etc.)
 *   <SkeletonCard />                  — pre-built card skeleton
 *   <SkeletonTable rows={5} cols={4} /> — table rows
 */

interface LineProps { width?: string; height?: string; className?: string }
export function SkeletonLine({ width = 'w-full', height = 'h-4', className = '' }: LineProps) {
  return <div className={`skeleton rounded ${height} ${width} ${className}`} />
}

interface BlockProps { height?: string; className?: string }
export function SkeletonBlock({ height = 'h-24', className = '' }: BlockProps) {
  return <div className={`skeleton rounded-lg ${height} w-full ${className}`} />
}

export function SkeletonCard() {
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center gap-3">
        <div className="skeleton w-8 h-8 rounded-full shrink-0" />
        <div className="flex-1 space-y-1.5">
          <SkeletonLine width="w-1/2" height="h-3.5" />
          <SkeletonLine width="w-1/3" height="h-3" />
        </div>
      </div>
      <SkeletonLine height="h-3" />
      <SkeletonLine width="w-4/5" height="h-3" />
      <SkeletonLine width="w-2/3" height="h-3" />
    </div>
  )
}

interface TableProps { rows?: number; cols?: number }
export function SkeletonTable({ rows = 5, cols = 4 }: TableProps) {
  return (
    <div className="space-y-2">
      {/* header */}
      <div className={`grid gap-3`} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
        {Array.from({ length: cols }).map((_, i) => (
          <SkeletonLine key={i} height="h-3" width="w-3/4" />
        ))}
      </div>
      {/* rows */}
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className={`grid gap-3`} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {Array.from({ length: cols }).map((_, c) => (
            <SkeletonLine key={c} height="h-4" width={c === 0 ? 'w-full' : 'w-4/5'} />
          ))}
        </div>
      ))}
    </div>
  )
}
