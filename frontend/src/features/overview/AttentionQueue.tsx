import type { Session, Task } from '../../lib/types'
import { SESSION_STATE_COLORS, TASK_STATE_COLORS } from '../../lib/constants'

interface AttentionQueueProps {
  pendingSessions: Session[]
  failedTasks: Task[]
}

export function AttentionQueue({ pendingSessions, failedTasks }: AttentionQueueProps) {
  const items = [
    ...pendingSessions.map(s => ({
      id: s.session_id,
      type: 'session' as const,
      title: `Session proposal from ${s.peer_id}`,
      subtitle: `Skills: ${s.proposed_skills.join(', ')}`,
      color: SESSION_STATE_COLORS[s.state] || 'var(--accent-yellow)',
      time: s.created_at,
    })),
    ...failedTasks.map(t => ({
      id: t.task_id,
      type: 'task' as const,
      title: `${t.skill} failed`,
      subtitle: t.error_message || `Peer: ${t.peer_name}`,
      color: TASK_STATE_COLORS[t.state] || 'var(--accent-red)',
      time: t.completed_at || t.created_at,
    })),
  ].sort((a, b) => (b.time || '').localeCompare(a.time || ''))

  if (items.length === 0) return null

  return (
    <div
      className="rounded-lg p-4 mb-6"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--accent-yellow)', borderLeftWidth: 3 }}
    >
      <h2 className="text-sm font-semibold mb-3" style={{ color: 'var(--accent-yellow)' }}>
        Needs Your Attention ({items.length})
      </h2>
      <div className="space-y-2">
        {items.slice(0, 5).map(item => (
          <div key={item.id} className="flex items-center gap-3 text-sm">
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: item.color }}
            />
            <div className="flex-1 min-w-0">
              <div className="truncate">{item.title}</div>
              <div className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                {item.subtitle}
              </div>
            </div>
            <span
              className="text-xs px-2 py-0.5 rounded capitalize"
              style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
            >
              {item.type}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
