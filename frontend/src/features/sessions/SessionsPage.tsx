import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchSessions, postSessionAction } from '../../lib/api/client'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/EmptyState'
import { TrustBadge } from '../../components/TrustBadge'
import { SESSION_STATE_COLORS } from '../../lib/constants'
import type { Session, SessionState } from '../../lib/types'

const STATE_FILTERS: Array<SessionState | 'all'> = ['all', 'proposed', 'active', 'closing', 'closed', 'completed', 'expired', 'rejected']

export function SessionsPage() {
  const [filter, setFilter] = useState<SessionState | 'all'>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: sessions, isLoading } = useQuery({
    queryKey: ['sessions', filter === 'all' ? undefined : filter],
    queryFn: () => fetchSessions(filter === 'all' ? undefined : { state: filter }),
  })

  const actionMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'accept' | 'reject' | 'close' }) =>
      postSessionAction(id, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })

  return (
    <div>
      <PageHeader
        title="Sessions"
        description="Collaboration sessions with peer agents"
      />

      <div className="flex gap-1 mb-4 flex-wrap">
        {STATE_FILTERS.map(s => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className="px-3 py-1.5 text-xs rounded-md capitalize transition-colors"
            style={{
              background: filter === s ? 'var(--accent-blue)' : 'var(--bg-tertiary)',
              color: filter === s ? 'var(--bg-primary)' : 'var(--text-secondary)',
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading...</div>
      ) : sessions && sessions.length > 0 ? (
        <div className="space-y-3">
          {sessions.map(session => (
            <SessionRow
              key={session.session_id}
              session={session}
              expanded={expanded === session.session_id}
              onToggle={() => setExpanded(expanded === session.session_id ? null : session.session_id)}
              onAction={(action) => actionMutation.mutate({ id: session.session_id, action })}
              acting={actionMutation.isPending}
            />
          ))}
        </div>
      ) : (
        <EmptyState title="No sessions" description={filter === 'all' ? 'No collaboration sessions yet' : `No ${filter} sessions`} />
      )}
    </div>
  )
}

interface SessionRowProps {
  session: Session
  expanded: boolean
  onToggle: () => void
  onAction: (action: 'accept' | 'reject' | 'close') => void
  acting: boolean
}

function SessionRow({ session, expanded, onToggle, onAction, acting }: SessionRowProps) {
  const stateColor = SESSION_STATE_COLORS[session.state] || 'var(--text-muted)'

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
    >
      <button
        onClick={onToggle}
        className="w-full text-left p-4 flex items-center justify-between"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: stateColor }} />
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{session.peer_id}</div>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {session.role} &middot; {new Date(session.created_at).toLocaleString()}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <TrustBadge tier={session.agreed_trust_tier} />
          <span
            className="text-xs px-2 py-0.5 rounded capitalize"
            style={{ background: stateColor, color: 'var(--bg-primary)' }}
          >
            {session.state}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t" style={{ borderColor: 'var(--border)' }}>
          <div className="grid grid-cols-2 gap-3 mt-3 text-xs">
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Skills: </span>
              {(session.agreed_skills?.length ? session.agreed_skills : session.proposed_skills).join(', ') || 'none'}
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Calls: </span>
              {session.call_count} / {session.agreed_max_calls}
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Tasks: </span>
              {session.tasks_completed} completed, {session.tasks_failed} failed
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Privacy: </span>
              {session.agreed_max_context_privacy}
            </div>
          </div>

          {session.state === 'proposed' && session.role === 'responder' && (
            <div className="flex gap-2 mt-3">
              <button
                onClick={() => onAction('accept')}
                disabled={acting}
                className="px-3 py-1.5 text-xs rounded"
                style={{ background: 'var(--accent-green)', color: 'var(--bg-primary)' }}
              >
                Accept
              </button>
              <button
                onClick={() => onAction('reject')}
                disabled={acting}
                className="px-3 py-1.5 text-xs rounded"
                style={{ background: 'var(--accent-red)', color: 'var(--bg-primary)' }}
              >
                Reject
              </button>
            </div>
          )}
          {session.state === 'active' && (
            <div className="mt-3">
              <button
                onClick={() => onAction('close')}
                disabled={acting}
                className="px-3 py-1.5 text-xs rounded"
                style={{ background: 'var(--accent-yellow)', color: 'var(--bg-primary)' }}
              >
                Close Session
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
