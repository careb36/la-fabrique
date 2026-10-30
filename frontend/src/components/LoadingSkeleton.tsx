/**
 * LoadingSkeleton — reusable loading placeholder.
 */

import { Loader2 } from 'lucide-react'

interface LoadingSkeletonProps {
  message?: string
  className?: string
}

export function LoadingSkeleton({ message, className = '' }: LoadingSkeletonProps) {
  return (
    <div className={`flex flex-col items-center justify-center p-8 ${className}`}>
      <Loader2 size={24} className="text-brand-400 animate-spin mb-3" />
      {message && <p className="text-sm text-gray-500">{message}</p>}
    </div>
  )
}

export function CardSkeleton() {
  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 animate-pulse">
      <div className="h-4 bg-surface-700 rounded w-1/3 mb-3" />
      <div className="h-3 bg-surface-700 rounded w-2/3 mb-2" />
      <div className="h-3 bg-surface-700 rounded w-1/2" />
    </div>
  )
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-10 bg-surface-800 rounded-lg animate-pulse" />
      ))}
    </div>
  )
}
