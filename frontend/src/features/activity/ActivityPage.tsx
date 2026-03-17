import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchActivity } from '../../lib/api/client'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/EmptyState'
import type { ActivityItem } from '../../lib/types'

const TYPE_FILTERS = ['all', 'message', 'task', 'session', 'trust', 'workflow'] as const
type TypeFilter = (typeof TYPE_FILTERS)[number]

const TYPE_COLORS: Record<string, string> = {
  task: 'var(--accent-blue)',
  session: 'var(--accent-green)',
  message: 'var(--accent-purple)',
  trust: 'var(--accent-yellow)',
  workflow: 'var(--accent-blue)',
}

const TYPE_ICONS: Record<string, string> = {
  task: 'T',
  session: 'S',
  message: 'M',
  trust: 'R',
  workflow: 'W',
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const color = TYPE_COLORS[item.type] || 'var(--text-muted)'
  return (
    <div
      className="flex items-start gap-3 py-3 px-4 rounded-lg"
      style={{ background: 'var(--bg-secondary)' }}
    >
      <span
        className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5"
        style={{ background: color, color: 'var(--bg-primary)', opacity: 0.9 }}
      >
        {TYPE_ICONS[item.type] || '?'}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate">{item.title || item.description}</div>
        {item.peer && (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {item.peer}
          </span>
        )}
      </div>
      <div className="text-xs flex-shrink-0" style={{ color: 'var(--text-muted)' }}>
        {formatRelativeTime(item.timestamp)}
      </div>
    </div>
  )
}

function formatRelativeTime(ts: string): string {
  if (!ts) return ''
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function ActivityPage() {
  const [filter, setFilter] = useState<TypeFilter>('all')

  const { data: activity, isLoading } = useQuery({
    queryKey: ['activity', 100],
    queryFn: () => fetchActivity(100),
  })

  const filtered =
    filter === 'all'
      ? activity || []
      : (activity || []).filter(item => item.type === filter)

  return (
    <div>
      <PageHeader
        title="Activity"
        description="Real-time event stream from your agent network"
      />

      {/* Filter bar */}
      <div className="flex gap-1 mb-4">
        {TYPE_FILTERS.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className="px-3 py-1.5 text-xs rounded-md capitalize transition-colors"
            style={{
              background: filter === f ? 'var(--accent-blue)' : 'var(--bg-tertiary)',
              color: filter === f ? 'var(--bg-primary)' : 'var(--text-secondary)',
            }}
          >
            {f}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading...</div>
      ) : filtered.length > 0 ? (
        <div className="space-y-2">
          {filtered.map(item => (
            <ActivityRow key={item.id || item.timestamp} item={item} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No activity"
          description={filter === 'all' ? 'Waiting for first event' : `No ${filter} events yet`}
        />
      )}
    </div>
  )
}
